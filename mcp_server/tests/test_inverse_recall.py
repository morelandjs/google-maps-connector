"""Inverse-recall eval against the real Google Maps Platform.

The inverse problem: start from KNOWN-GOOD places (NYC, rating > 4.5 with
200+ reviews, curated 2026-07-15 across bars / restaurants / music / comedy /
museums / activity venues), each paired with the query an agent *should*
plausibly issue to find it and the anchor it would naturally use. Recall =
the fraction of seeds actually returned by their own inverse query. Where
`test_live_smoke.py` checks shape ("at least one result"), this measures
retrieval QUALITY — a schema or query-construction regression shows up here
as a recall drop long before any shape test fails.

Like the live smoke tests these are SKIPPED by default; they spend real
Places quota (~1 searchText call per anchor group) and, for the events leg,
real Gemini + Playwright time. Run with:

    RUN_LIVE_TESTS=1 .venv/bin/pytest tests/test_inverse_recall.py -v -s

Thresholds are deliberately below 1.0: Google's ranking breathes, places
close, events expire. A seed that fails persistently means either the seed
went stale (re-curate it) or retrieval genuinely regressed — read the
printed per-seed report to tell which.

Regenerating seeds (fixtures/inverse_recall_nyc.json): run broad category
sweeps through `search_nearby_places`, keep places with rating > 4.5 and
>= 200 ratings, then write one entry per place with the concept query an
agent would use (location-free, per the tool schema) and a neighborhood
anchor. Event seeds come from one `get_events` batch over seed venues that
post schedules; they carry start_date and are skipped once past.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re

import pytest

import server

LIVE_ENABLED = os.environ.get("RUN_LIVE_TESTS") == "1"
HAS_REAL_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "") not in {
    "",
    "TEST_KEY",
    "YOUR_API_KEY",
    "YOUR_KEY",
}

pytestmark = [
    pytest.mark.skipif(
        not LIVE_ENABLED,
        reason="set RUN_LIVE_TESTS=1 to run live tests against real Google APIs",
    ),
    pytest.mark.skipif(
        not HAS_REAL_KEY,
        reason="GOOGLE_MAPS_API_KEY missing or set to a placeholder — "
        "fill .env with a real key before running live tests",
    ),
]

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "inverse_recall_nyc.json"

PLACE_RECALL_FLOOR = 0.6
EVENT_RECALL_FLOOR = 0.5


def _sections_by_place_id(markdown: str) -> dict[str, tuple[int, str]]:
    """Map place_id -> (rank, section text) for one tool response."""
    out: dict[str, tuple[int, str]] = {}
    for match in re.finditer(
        r"^## (\d+)\. .*?(?=^## \d+\. |\Z)", markdown, flags=re.M | re.S
    ):
        section = match.group(0)
        pid = re.search(r"- \*\*Place ID:\*\* (\S+)", section)
        if pid:
            out[pid.group(1)] = (int(match.group(1)), section)
    return out


def _matched_queries(section: str) -> list[str] | None:
    line = re.search(r"- \*\*Matched:\*\* (.+)", section)
    if line is None:
        return None  # single-query call — no Matched line emitted
    return [q.strip() for q in line.group(1).split(",")]


def _normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


async def test_place_inverse_recall():
    seeds = json.loads(FIXTURE.read_text())["place_seeds"]

    # Seeds sharing an anchor ride the same tool call, mirroring how an
    # agent batches concept queries against one location.
    by_anchor: dict[str, list[dict]] = {}
    for seed in seeds:
        by_anchor.setdefault(seed["anchor"]["area_name"], []).append(seed)

    report: list[str] = []
    recovered = 0
    for anchor, group in by_anchor.items():
        markdown = await server.search_nearby_places(
            queries=[s["inverse_query"] for s in group],
            area_name=anchor,
            max_results=10,
        )
        sections = _sections_by_place_id(markdown)
        for seed in group:
            hit = sections.get(seed["place_id"])
            matched = hit and (
                (mq := _matched_queries(hit[1])) is None
                or seed["inverse_query"] in mq
            )
            if matched:
                recovered += 1
                report.append(
                    f"  HIT  rank {hit[0]:>2}  {seed['name']}  "
                    f"[{seed['inverse_query']!r} @ {anchor}]"
                )
            else:
                why = "returned but by another query" if hit else "not returned"
                report.append(
                    f"  MISS ({why})  {seed['name']}  "
                    f"[{seed['inverse_query']!r} @ {anchor}]"
                )

    fraction = recovered / len(seeds)
    summary = (
        f"place inverse recall: {recovered}/{len(seeds)} = {fraction:.0%}\n"
        + "\n".join(sorted(report))
    )
    print("\n" + summary)
    assert fraction >= PLACE_RECALL_FLOOR, summary


HAS_REAL_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "") not in {
    "",
    "TEST_GEMINI_KEY",
    "YOUR_AI_STUDIO_KEY",
}


@pytest.mark.skipif(
    not HAS_REAL_GEMINI_KEY,
    reason="GEMINI_API_KEY missing or set to a placeholder — "
    "fill .env with a real AI Studio key before running live get_events",
)
async def test_event_inverse_recall():
    """Known events on seed venues' websites should still be extracted.

    Ground truth was captured by a get_events run at fixture-generation
    time, so this measures drift: site redesigns, extraction regressions,
    scraper breakage. Seeds whose start_date has passed are excluded —
    when all have expired the test skips and the fixture needs regenerating.
    """
    seeds = json.loads(FIXTURE.read_text())["event_seeds"]
    today = datetime.date.today().isoformat()
    live_seeds = [s for s in seeds if s["start_date"] >= today]
    if not live_seeds:
        pytest.skip("all event seeds expired — regenerate the fixture")

    websites = sorted({s["website"] for s in live_seeds})
    result = await server.get_events(websites=websites)

    report: list[str] = []
    recovered = 0
    for seed in live_seeds:
        extracted = result.get(seed["website"])
        hit = False
        # An event is identified by (when, who/what). Titles are LLM-derived
        # and re-paraphrase from run to run, so match on same start_date plus
        # majority token overlap with the seed title, not string equality.
        if isinstance(extracted, list):
            want = set(_normalize(seed["event_title"]).split())
            for event in extracted:
                if event["start_date"] != seed["start_date"]:
                    continue
                got = set(_normalize(event["event_title_derived"]).split())
                if want and len(want & got) / len(want) >= 0.5:
                    hit = True
                    break
        if hit:
            recovered += 1
        status = "HIT " if hit else "MISS"
        if isinstance(extracted, dict):
            status = f"MISS (site error: {extracted.get('error')})"
        report.append(
            f"  {status}  {seed['event_title']!r} ({seed['start_date']}) "
            f"on {seed['website']}"
        )

    fraction = recovered / len(live_seeds)
    summary = (
        f"event inverse recall: {recovered}/{len(live_seeds)} = {fraction:.0%} "
        f"({len(seeds) - len(live_seeds)} expired seeds excluded)\n"
        + "\n".join(sorted(report))
    )
    print("\n" + summary)
    assert fraction >= EVENT_RECALL_FLOOR, summary
