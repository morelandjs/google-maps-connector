#!/usr/bin/env python3
"""Local end-to-end UX test for the MCP connector.

Drives REAL headless Claude sessions (`claude -p`) with the local MCP server
attached over stdio — the closest local approximation of Claude Mobile using
the connector. Each scenario is a realistic user message tagged with the
tool signature we EXPECT ("places", "events", "both", or "either"); the
harness records which tools Claude called, with what arguments, and the
final prose answer, then prints an expected-vs-actual scorecard.

Usage:
    python3 ux_test.py                     # run all scenarios (3 in parallel)
    python3 ux_test.py date_night bagels   # run selected scenarios
    python3 ux_test.py --workers 1 ...     # serial

Requires: `claude` CLI on PATH, real keys in mcp_server/.env, and
`playwright install chromium` in mcp_server/.venv. Results land in
ux_results/<scenario>.md (gitignored); nothing here runs in CI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent
SERVER_DIR = REPO / "mcp_server"
RESULTS_DIR = REPO / "ux_results"

PLACES = "mcp__gmaps__search_nearby_places"
EVENTS = "mcp__gmaps__get_events"
ROUTE = "mcp__gmaps__get_route"

# expect: "places" = search only (get_events would be wasteful),
#         "events" = must include a get_events call,
#         "both"   = must include search AND get_events,
#         "either" = genuinely ambiguous; grade by reading the transcript.
SCENARIOS: dict[str, dict] = {
    # ---- original five ----
    "place_search": {
        "prompt": "What are some good coffee shops near Washington Square Park?",
        "expect": "places",
    },
    "directions": {
        "prompt": "How do I get from Union Square to Prospect Park on the "
        "subway? I need to be there by 3pm.",
        "expect": "route",
    },
    "venue_events": {
        "prompt": "What's going on at Zeppelin Hall in Jersey City this week?",
        "expect": "events",
    },
    "date_night": {
        "prompt": "My partner and I want fun date night ideas in Jersey City "
        "this weekend. What's actually happening?",
        "expect": "both",
    },
    "recommendation": {
        "prompt": "Where should I take my parents for dinner in the West "
        "Village? They love Italian food.",
        "expect": "places",
    },
    "outing_not_event": {
        "prompt": "I'm planning a little event for my coworkers Thursday "
        "after work — thinking a driving range or mini golf kind of place in "
        "Jersey City. Where should we go?",
        "expect": "places",
    },
    "social_events": {
        "prompt": "I just moved to Jersey City and want to meet people and "
        "make friends. Anything social going on this week I could join?",
        "expect": "both",
    },
    # ---- NYC optimization sweep ----
    "bagels": {
        "prompt": "Best bagels near Columbus Circle?",
        "expect": "places",
    },
    "late_coffee": {
        "prompt": "I need a coffee shop in the East Village that's open past "
        "10pm where I can sit and work.",
        "expect": "places",
    },
    "comedy_tonight": {
        "prompt": "Any comedy shows in the West Village tonight?",
        "expect": "both",
    },
    "named_venue_week": {
        "prompt": "What's playing at Nitehawk Cinema in Williamsburg this week?",
        "expect": "events",
    },
    "birthday_dinner": {
        "prompt": "I'm organizing a birthday dinner for 8 people in "
        "Williamsburg next Friday. Somewhere fun but where we can actually "
        "talk. Ideas?",
        "expect": "places",
    },
    "salsa": {
        "prompt": "I want to learn salsa — any classes or dance socials in "
        "Manhattan this week?",
        "expect": "both",
    },
    "kid_saturday": {
        "prompt": "What can I do with my 5-year-old in Park Slope Saturday "
        "morning?",
        "expect": "either",
    },
    "jazz_tonight": {
        "prompt": "Live jazz in Harlem tonight — where should I go?",
        "expect": "both",
    },
    "trivia_astoria": {
        "prompt": "Which bars around Astoria have trivia nights this week?",
        "expect": "both",
    },
    "first_date": {
        "prompt": "First date Thursday in SoHo. Looking for a low-pressure "
        "drinks spot, not too loud.",
        "expect": "places",
    },
    "markets": {
        "prompt": "Are there any good farmers markets or flea markets "
        "happening in Brooklyn this weekend?",
        "expect": "both",
    },
    "gallery_openings": {
        "prompt": "Any gallery openings or new exhibitions in Chelsea this "
        "week?",
        "expect": "both",
    },
    "rainy_day": {
        "prompt": "It's supposed to rain all day tomorrow. What can I do "
        "indoors around Midtown?",
        "expect": "either",
    },
    "bored_bushwick": {
        "prompt": "I'm bored of my usual bars. Anything special or weird "
        "happening in Bushwick on Friday?",
        "expect": "both",
    },
    "pottery": {
        "prompt": "I want to try a pottery or art class in Brooklyn — "
        "something I can just drop into.",
        "expect": "both",
    },
    "rooftop_lic": {
        "prompt": "Rooftop bars with a good skyline view near Long Island "
        "City?",
        "expect": "places",
    },
    "author_readings": {
        "prompt": "Which Manhattan bookstores have author readings or "
        "signings coming up this month?",
        "expect": "both",
    },
    "run_clubs": {
        "prompt": "Are there run clubs or group workouts meeting near "
        "Central Park this week I could join?",
        "expect": "both",
    },
    "visitor_saturday": {
        "prompt": "My friend is visiting next Saturday. Plan us a fun day in "
        "Greenwich Village: brunch spot, something cultural in the "
        "afternoon, and a show or live music at night.",
        "expect": "both",
    },
}

MCP_TOOLS = [PLACES, ROUTE, EVENTS]


def read_env_keys() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (SERVER_DIR / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k in ("GOOGLE_MAPS_API_KEY", "GEMINI_API_KEY"):
                env[k] = v.strip().strip('"')
    missing = {"GOOGLE_MAPS_API_KEY", "GEMINI_API_KEY"} - set(env)
    if missing:
        raise SystemExit(f"missing keys in mcp_server/.env: {missing}")
    return env


def write_mcp_config(env: dict[str, str]) -> str:
    config = {
        "mcpServers": {
            "gmaps": {
                "command": str(SERVER_DIR / ".venv" / "bin" / "python"),
                "args": [str(SERVER_DIR / "server.py"), "--stdio"],
                "env": env,
            }
        }
    }
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="gmaps-mcp-"
    )
    json.dump(config, f)
    f.close()
    return f.name


def grade(expect: str, tools: set[str]) -> str:
    if expect == "places":
        return "PASS" if PLACES in tools and EVENTS not in tools else "FAIL"
    if expect == "events":
        return "PASS" if EVENTS in tools else "FAIL"
    if expect == "both":
        return "PASS" if PLACES in tools and EVENTS in tools else "FAIL"
    if expect == "route":
        return "PASS" if ROUTE in tools else "FAIL"
    return "REVIEW"  # "either" — judge from the transcript


def run_scenario(key: str, spec: dict, mcp_config: str) -> dict:
    import time

    prompt = spec["prompt"]
    start = time.monotonic()
    print(f"=== {key}: {prompt[:70]}...")
    cmd = [
        "claude",
        "-p",
        prompt,
        "--mcp-config",
        mcp_config,
        "--strict-mcp-config",
        "--allowedTools",
        ",".join(MCP_TOOLS),
        "--max-turns",
        "15",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    # Event scenarios can legitimately run long: get_events paces its Gemini
    # calls (budget 210s) before Claude synthesizes.
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900, cwd=REPO
        )
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr, rc = "HARNESS TIMEOUT (900s)", -1

    tool_calls: list[dict] = []
    finals: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tool_calls.append(
                        {"tool": block.get("name"), "input": block.get("input")}
                    )
        elif event.get("type") == "result":
            finals.append(event.get("result") or "")

    tools_used = {c["tool"] for c in tool_calls}
    verdict = grade(spec["expect"], tools_used)
    elapsed = time.monotonic() - start

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{key}.md"
    lines = [
        f"# {key}",
        "",
        f"**User:** {prompt}",
        "",
        f"**Expected:** {spec['expect']}  **Verdict:** {verdict}  "
        f"**Elapsed:** {elapsed:.0f}s",
        "",
        "## Tool calls",
        "",
    ]
    if not tool_calls:
        lines.append("(none — Claude answered from prior knowledge!)")
    for i, call in enumerate(tool_calls, 1):
        lines.append(f"### {i}. `{call['tool']}`")
        lines.append("```json")
        lines.append(json.dumps(call["input"], indent=2)[:3000])
        lines.append("```")
    lines += ["", "## Final response", "", finals[-1] if finals else "(none)"]
    if rc != 0:
        lines += ["", "## stderr", "", (stderr or "")[-2000:]]
    out.write_text("\n".join(lines))
    print(
        f"    [{verdict}] {key} ({elapsed:.0f}s): "
        f"{sorted(t.split('__')[-1] for t in tools_used)}"
    )
    return {"key": key, "expect": spec["expect"], "verdict": verdict,
            "tools": sorted(tools_used), "elapsed": elapsed,
            "answered": bool(finals and finals[-1])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("keys", nargs="*", default=[])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    keys = args.keys or list(SCENARIOS)
    env = read_env_keys()
    mcp_config = write_mcp_config(env)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(
            pool.map(lambda k: run_scenario(k, SCENARIOS[k], mcp_config), keys)
        )

    print("\n===== SCOREBOARD =====")
    for r in results:
        tools = ",".join(t.split("__")[-1] for t in r["tools"] if t.startswith("mcp"))
        answered = "" if r["answered"] else "  (NO FINAL ANSWER)"
        print(f"{r['verdict']:>6}  {r['key']:<20} {r['elapsed']:>4.0f}s "
              f"expect={r['expect']:<7} used=[{tools}]{answered}")
    fails = [r for r in results if r["verdict"] == "FAIL" or not r["answered"]]
    print(f"\n{len(results) - len(fails)}/{len(results)} clean")


if __name__ == "__main__":
    main()
