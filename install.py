#!/usr/bin/env python3
"""Personal Google Maps MCP installer.

Walks a new user from "signed in to Google Cloud" to a deployed, OAuth-protected
MCP endpoint in their own GCP account. ~10 minutes, one browser-only step.

Usage:
    python install.py
    python install.py --project-id my-id   # use a specific project ID
    python install.py --reset              # discard saved state, start over

The installer is resumable: if any step fails, fix the issue and re-run — it
picks up where it left off using a state file at:
    ~/.config/google-maps-mcp/install-state.json

Stdlib only. No `pip install` needed before running.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import re
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

# ---------- Constants ----------

REPO_ROOT = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".config" / "google-maps-mcp"
STATE_PATH = STATE_DIR / "install-state.json"
LOG_PATH = STATE_DIR / "install.log"

DEFAULT_REGION = "us-central1"
DEFAULT_SERVICE_NAME = "google-maps-mcp"
DEFAULT_PROJECT_NAME = "Google Maps MCP Server"

REQUIRED_APIS = [
    "places.googleapis.com",
    "routes.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "apikeys.googleapis.com",
    # Lets the Gemini (AI Studio) key live in THIS project instead of AI
    # Studio auto-creating a separate one — so everything stays consolidated.
    "generativelanguage.googleapis.com",
]

SECRET_NAMES = [
    "GOOGLE_MAPS_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_ALLOWED_EMAILS",
]


# ---------- Visual helpers ----------


class Colors:
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def _color_supported() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def color(text: str, c: str) -> str:
    return f"{c}{text}{Colors.RESET}" if _color_supported() else text


def info(msg: str) -> None:
    print(f"  {msg}")


def success(msg: str) -> None:
    print(f"  {color('✓', Colors.GREEN)} {msg}")


def warn(msg: str) -> None:
    print(f"  {color('⚠', Colors.YELLOW)} {msg}")


def error(msg: str) -> None:
    print(f"  {color('✗', Colors.RED)} {msg}", file=sys.stderr)


def die(msg: str, code: int = 1) -> None:
    error(msg)
    sys.exit(code)


# ---------- Prompts ----------


def prompt(question: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        ans = input(f"  {question}{suffix}: ").strip()
        if ans:
            return ans
        if default is not None:
            return default
        info("(empty input not allowed)")


def prompt_secret(
    question: str,
    *,
    hidden: bool = False,
    validator: Callable[[str], bool] | None = None,
    hint: str = "",
) -> str:
    while True:
        if hidden:
            ans = getpass.getpass(f"  {question}: ").strip()
        else:
            ans = input(f"  {question}: ").strip()
        if not ans:
            info("(empty input not allowed)")
            continue
        if validator and not validator(ans):
            info(f"  invalid format. {hint}".rstrip())
            continue
        return ans


def confirm(question: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    ans = input(f"  {question}{suffix}: ").strip().lower()
    if not ans:
        return default
    return ans in ("y", "yes")


# ---------- gcloud helper ----------


class GcloudError(RuntimeError):
    pass


def _log_cmd(cmd: list[str]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {' '.join(cmd)}\n")


def gcloud(
    args: list[str],
    *,
    stdin: str | None = None,
    capture: bool = True,
    check: bool = True,
) -> str:
    """Run gcloud, return stdout. Raises GcloudError on failure."""
    full = ["gcloud"] + args
    _log_cmd(full)
    if capture:
        result = subprocess.run(full, input=stdin, text=True, capture_output=True)
    else:
        result = subprocess.run(full, input=stdin, text=True)
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip() if capture else ""
        head = " ".join(args[:3]) + ("..." if len(args) > 3 else "")
        raise GcloudError(
            f"gcloud {head} failed (exit {result.returncode}): "
            f"{stderr or 'see output above'}"
        )
    return (result.stdout or "") if capture else ""


def gcloud_installed() -> bool:
    return subprocess.run(["which", "gcloud"], capture_output=True).returncode == 0


# ---------- State ----------


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


# ---------- Validators ----------

PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"
CLIENT_SECRET_PREFIX = "GOCSPX-"


# GCP rejects project IDs containing these substrings (fails at create time
# with an opaque "prohibited words" error — catch it up front instead).
PROHIBITED_PROJECT_WORDS = ("google", "ssl", "goog")


def valid_project_id(s: str) -> bool:
    if not PROJECT_ID_RE.match(s):
        return False
    return not any(w in s.lower() for w in PROHIBITED_PROJECT_WORDS)


def valid_emails(s: str) -> bool:
    parts = [e.strip() for e in s.split(",") if e.strip()]
    return bool(parts) and all(EMAIL_RE.match(p) for p in parts)


def random_suffix(length: int = 5) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


# ---------- Secret-Manager helper ----------


def validate_gemini_key(key: str) -> str:
    """Live-check a pasted Gemini key with a one-token call.

    Returns 'ok', 'quota' (valid key, free-tier limit hit), 'invalid', or
    'unknown' (network trouble — don't block the install on it).
    """
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.1-flash-lite:generateContent",
        data=json.dumps(
            {"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}
        ).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        return "ok"
    except urllib.error.HTTPError as e:
        return "quota" if e.code == 429 else "invalid"
    except urllib.error.URLError:
        return "unknown"


def push_secret_value(name: str, value: str, project_id: str) -> None:
    """Create the secret if absent, then add a new version with the given value.

    Pipes the value via stdin so it never appears in argv (and never reaches
    the install.log).
    """
    check = subprocess.run(
        ["gcloud", "secrets", "describe", name, f"--project={project_id}"],
        capture_output=True,
    )
    if check.returncode != 0:
        subprocess.run(
            [
                "gcloud", "secrets", "create", name,
                "--replication-policy=automatic", f"--project={project_id}",
            ],
            check=True, capture_output=True,
        )
    subprocess.run(
        [
            "gcloud", "secrets", "versions", "add", name,
            "--data-file=-", f"--project={project_id}",
        ],
        input=value, text=True, check=True, capture_output=True,
    )


# ---------- Step registry ----------

STEPS: list[tuple[str, Callable]] = []


def step(title: str):
    def deco(fn):
        STEPS.append((title, fn))
        return fn

    return deco


# ---------- Steps ----------


@step("Check prerequisites")
def step_check_prereqs(state, args):
    if not gcloud_installed():
        die(
            "gcloud CLI not found. Install it from "
            "https://cloud.google.com/sdk/docs/install and re-run."
        )
    if sys.version_info < (3, 11):
        die(
            f"Python 3.11+ required (you have "
            f"{sys.version_info[0]}.{sys.version_info[1]})."
        )
    success("gcloud + Python 3.11+ present")


@step("Sign in to Google Cloud")
def step_auth_login(state, args):
    out = gcloud(
        ["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"]
    )
    active = [x for x in out.strip().splitlines() if x]
    if active:
        info(f"Currently signed in as: {active[0]}")
        if confirm("Use this account?", default=True):
            state["account"] = active[0]
            success(f"using {active[0]}")
            return
    info("Opening browser for Google sign-in...")
    gcloud(["auth", "login"], capture=False)
    out = gcloud(
        ["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"]
    )
    state["account"] = out.strip().splitlines()[0]
    success(f"signed in as {state['account']}")


@step("Pick or create a GCP project")
def step_select_project(state, args):
    if args.project_id:
        if not valid_project_id(args.project_id):
            die(f"Invalid project ID: {args.project_id!r}")
        check = subprocess.run(
            ["gcloud", "projects", "describe", args.project_id],
            capture_output=True,
        )
        if check.returncode != 0:
            info(f"Creating project {args.project_id}...")
            gcloud(
                ["projects", "create", args.project_id, "--name", DEFAULT_PROJECT_NAME],
                capture=False,
            )
        state["project_id"] = args.project_id
    else:
        out = gcloud(["projects", "list", "--format=value(projectId,name)"])
        projects = [
            line.split("\t") for line in out.strip().splitlines() if line
        ]

        if projects:
            info("Existing projects:")
            for i, parts in enumerate(projects, 1):
                pid = parts[0]
                pname = parts[1] if len(parts) > 1 else ""
                print(f"      {i}) {pid}  ({pname})")
        new_idx = len(projects) + 1
        print(f"      {new_idx}) Create a new project")

        while True:
            choice = prompt("Choice", default=str(new_idx))
            try:
                n = int(choice)
            except ValueError:
                info("(enter a number)")
                continue
            if 1 <= n <= len(projects):
                state["project_id"] = projects[n - 1][0]
                break
            elif n == new_idx:
                # GCP forbids the substring "google" (and "ssl", "goog") in
                # project IDs, so the default must NOT be "google-maps-...".
                default_id = f"maps-mcp-{random_suffix()}"
                while True:
                    pid = prompt(
                        "New project ID (6-30 chars, lowercase letters/digits/hyphens)",
                        default=default_id,
                    )
                    if valid_project_id(pid):
                        break
                    info("invalid format; try again")
                pname = prompt("Display name", default=DEFAULT_PROJECT_NAME)
                info(f"Creating project {pid}...")
                gcloud(["projects", "create", pid, "--name", pname], capture=False)
                state["project_id"] = pid
                break
            else:
                info("invalid choice")

    out = gcloud(
        [
            "projects", "describe", state["project_id"],
            "--format=value(projectNumber)",
        ]
    )
    state["project_number"] = out.strip()
    info(f"Project number: {state['project_number']}")
    gcloud(["config", "set", "project", state["project_id"]])
    success(f"using {state['project_id']}")


@step("Confirm billing account is linked")
def step_billing(state, args):
    # Use GA `gcloud billing` (not `beta`) — beta triggers a hidden
    # component-install prompt on first use that looks like a freeze.
    pid = state["project_id"]
    out = subprocess.run(
        [
            "gcloud", "billing", "projects", "describe", pid,
            "--format=value(billingEnabled)",
        ],
        capture_output=True, text=True,
    )
    if out.returncode == 0 and "True" in out.stdout:
        success("billing already linked")
        return

    info("Project does not have a billing account linked.")
    warn(
        "💰 Linking billing is what makes charges POSSIBLE. Expected here: "
        "~$0.10/mo (image storage); Maps stays in free caps at personal scale."
    )
    info("Open this URL in your browser:")
    info(f"  https://console.cloud.google.com/billing/linkedaccount?project={pid}")
    info("Link (or create) a billing account, then return here.")
    input("  Press Enter when done...")

    out = gcloud(
        [
            "billing", "projects", "describe", pid,
            "--format=value(billingEnabled)",
        ]
    )
    if "True" not in out:
        die("billing still not enabled. Re-run after linking.")
    success("billing linked")


@step("Enable required APIs")
def step_enable_apis(state, args):
    info(f"Enabling {len(REQUIRED_APIS)} APIs (~30s)...")
    gcloud(
        ["services", "enable", "--project", state["project_id"], *REQUIRED_APIS],
        capture=False,
    )
    success("APIs enabled")


@step("Create Google Maps API key")
def step_create_api_key(state, args):
    pid = state["project_id"]

    if state.get("maps_api_key_pushed"):
        success("already created in a prior run")
        return

    list_out = gcloud(
        [
            "services", "api-keys", "list",
            "--filter=displayName=Google Maps MCP",
            f"--project={pid}",
            "--format=value(name)",
        ]
    )
    existing = [x for x in list_out.strip().splitlines() if x]
    if existing:
        info("Found existing key with display name 'Google Maps MCP'")
        if confirm("Reuse it?", default=True):
            key_name = existing[0]
            key_str = gcloud(
                [
                    "services", "api-keys", "get-key-string", key_name,
                    "--format=value(keyString)",
                ]
            ).strip()
            state["maps_api_key_name"] = key_name
            push_secret_value("GOOGLE_MAPS_API_KEY", key_str, pid)
            state["maps_api_key_pushed"] = True
            success("reused existing key, pushed to Secret Manager")
            return

    info("Creating restricted Maps API key...")
    out = gcloud(
        [
            "services", "api-keys", "create",
            "--display-name=Google Maps MCP",
            f"--project={pid}",
            "--api-target=service=places.googleapis.com",
            "--api-target=service=routes.googleapis.com",
            "--format=json",
        ]
    )
    data = json.loads(out)
    name = data.get("name", "")
    if name.startswith("operations/"):
        name = (data.get("response") or {}).get("name", "")
    if not name:
        die(f"Could not parse API key resource name from output:\n{out[:300]}")

    key_str = gcloud(
        [
            "services", "api-keys", "get-key-string", name,
            "--format=value(keyString)",
        ]
    ).strip()
    state["maps_api_key_name"] = name
    push_secret_value("GOOGLE_MAPS_API_KEY", key_str, pid)
    state["maps_api_key_pushed"] = True
    success("key created, restricted to Places + Routes, pushed to Secret Manager")


@step("Create Gemini API key (for get_events)")
def step_gemini_key(state, args):
    pid = state["project_id"]

    if state.get("gemini_api_key_pushed"):
        success("already configured in a prior run")
        return

    # An AI Studio key and a Cloud API key are the same object, so we mint one
    # in THIS project restricted to the Gemini API — no aistudio.google.com
    # visit, no paste, billing consolidated (needs generativelanguage.googleapis
    # .com, enabled in step_enable_apis).
    info("Event scraping (get_events) uses Gemini.")
    warn(
        "💰 With billing on this project, event search costs ~$0.05-0.15 each. "
        "Free tier = 20 requests/day ≈ 1-2 searches before it rate-limits."
    )

    list_out = gcloud(
        [
            "services", "api-keys", "list",
            "--filter=displayName=Gemini MCP",
            f"--project={pid}",
            "--format=value(name)",
        ]
    )
    existing = [x for x in list_out.strip().splitlines() if x]
    if existing and confirm("Reuse existing 'Gemini MCP' key?", default=True):
        name = existing[0]
    else:
        info("Creating restricted Gemini API key...")
        out = gcloud(
            [
                "services", "api-keys", "create",
                "--display-name=Gemini MCP",
                f"--project={pid}",
                "--api-target=service=generativelanguage.googleapis.com",
                "--format=json",
            ]
        )
        data = json.loads(out)
        name = data.get("name", "")
        if name.startswith("operations/"):
            name = (data.get("response") or {}).get("name", "")
        if not name:
            die(f"Could not parse API key resource name from output:\n{out[:300]}")

    key_str = gcloud(
        [
            "services", "api-keys", "get-key-string", name,
            "--format=value(keyString)",
        ]
    ).strip()

    verdict = validate_gemini_key(key_str)
    if verdict == "ok":
        success("key verified with a live Gemini call")
    elif verdict == "quota":
        warn("key valid but rate-limited right now (free tier) — fine, it works")
    elif verdict == "invalid":
        # A brand-new key can lag a few seconds before it's live.
        warn("key not accepted yet (may need a moment to propagate); storing it")
    else:
        warn("could not reach the Gemini API to verify; storing the key anyway")

    state["gemini_api_key_name"] = name
    push_secret_value("GEMINI_API_KEY", key_str, pid)
    state["gemini_api_key_pushed"] = True
    success("key created, restricted to Gemini, pushed to Secret Manager")


@step("Compute predicted Cloud Run URL")
def step_predict_url(state, args):
    region = args.region
    service_name = args.service_name
    project_number = state["project_number"]

    base_url = f"https://{service_name}-{project_number}.{region}.run.app"
    callback = f"{base_url}/auth/callback"

    state["region"] = region
    state["service_name"] = service_name
    state["mcp_base_url"] = base_url
    state["oauth_redirect_uri"] = callback

    info(f"MCP base URL (predicted): {base_url}")
    info(f"OAuth callback URL:       {callback}")


@step("Configure OAuth (single browser visit)")
def step_oauth(state, args):
    if state.get("oauth_credentials_pushed"):
        success("already configured in a prior run")
        return

    pid = state["project_id"]
    redirect = state["oauth_redirect_uri"]
    account = state.get("account", "<your email>")

    print()
    print("  ╭───────────────────────────────────────────────────────────╮")
    print("  │ One browser-only step. ~4 minutes, all in one tab.        │")
    print("  │ Google requires manual OAuth consent screen + Client      │")
    print("  │ creation — there's no API for either.                     │")
    print("  ╰───────────────────────────────────────────────────────────╯")
    print()
    print("  STEP A — OAuth consent screen")
    print(
        f"    Open: https://console.cloud.google.com/apis/credentials/consent?project={pid}"
    )
    print("    1) Click 'Get Started' (or skip past if already configured)")
    print("    2) User Type: External  →  Create")
    print(f"    3) App name: {DEFAULT_PROJECT_NAME}")
    print(f"    4) Support email: {account}")
    print("    5) Add scopes — click 'Add or remove scopes', tick:")
    print("         openid")
    print("         .../auth/userinfo.email")
    print(f"    6) Add yourself ({account}) as a test user")
    print("    7) Save & continue through to 'Back to dashboard'")
    print()
    input("  Press Enter when done with the consent screen...")

    print()
    print("  STEP B — OAuth 2.0 Client ID")
    print(
        f"    Open: https://console.cloud.google.com/apis/credentials?project={pid}"
    )
    print("    1) Click '+ Create Credentials' → 'OAuth client ID'")
    print("    2) Application type: Web application")
    print(f"    3) Name: {DEFAULT_PROJECT_NAME}")
    print("    4) Authorized redirect URIs → '+ ADD URI', paste exactly:")
    print(f"         {redirect}")
    print("    5) Click Create. A modal pops up with Client ID + Secret.")
    print()

    client_id = prompt_secret(
        "Paste Client ID",
        validator=lambda x: x.endswith(CLIENT_ID_SUFFIX) and len(x) > 30,
        hint=f"must end in {CLIENT_ID_SUFFIX}",
    )
    client_secret = prompt_secret(
        "Paste Client Secret",
        hidden=True,
        validator=lambda x: x.startswith(CLIENT_SECRET_PREFIX) and len(x) > 10,
        hint=f"must start with {CLIENT_SECRET_PREFIX}",
    )

    push_secret_value("GOOGLE_OAUTH_CLIENT_ID", client_id, pid)
    push_secret_value("GOOGLE_OAUTH_CLIENT_SECRET", client_secret, pid)
    state["oauth_credentials_pushed"] = True
    success("OAuth credentials pushed to Secret Manager")


@step("Configure single-tenant email allowlist")
def step_allowlist(state, args):
    pid = state["project_id"]

    if state.get("allowed_emails_pushed"):
        success(f"already set: {state.get('allowed_emails')}")
        return

    if args.allowed_emails:
        emails = args.allowed_emails
        if not valid_emails(emails):
            die(f"Invalid --allowed-emails value: {emails}")
    else:
        default = state.get("account", "")
        while True:
            emails = prompt(
                "Email(s) allowed to authenticate (comma-separated)",
                default=default,
            )
            if valid_emails(emails):
                break
            info("at least one email looks invalid; try again")

    push_secret_value("GOOGLE_OAUTH_ALLOWED_EMAILS", emails, pid)
    state["allowed_emails"] = emails
    state["allowed_emails_pushed"] = True
    success(f"allowlist set: {emails}")


@step("Personalize: results language")
def step_language(state, args):
    """All tool results come back in this language, wherever the places are —
    Google localizes Places/Routes natively; event extraction translates."""
    info("Your preferred language for results. This matters most when you're")
    info("TRAVELING ABROAD: event listings are scraped straight off venues'")
    info("websites, so a Paris venue's site is in French — set this to 'en' and")
    info("those events come back translated to English. (Place names and")
    info("directions are localized by Google automatically either way.)")
    if args.language:
        lang = args.language
    else:
        lang = prompt(
            "Language you want results in — BCP-47 code (en, es, fr, de, ja, ...)",
            default=state.get("language", "en"),
        )
    if not re.fullmatch(r"[a-z]{2,3}(-[A-Z]{2})?", lang):
        die(f"'{lang}' is not a BCP-47 code like 'en' or 'pt-BR'. Re-run.")
    state["language"] = lang
    success(f"results language: {lang}")


@step("Personalize: default travel mode")
def step_travel_mode(state, args):
    """Used by get_route whenever the user doesn't say how they're
    travelling — a New Yorker wants TRANSIT, a driver wants DRIVE."""
    info("This is how YOU usually get around. When you ask for directions")
    info("without saying how ('how do I get to X?'), the connector assumes this")
    info("— a NYC subway rider picks TRANSIT; someone who drives picks DRIVE.")
    if args.travel_mode:
        mode = args.travel_mode.upper()
    else:
        mode = prompt(
            "How you usually travel (TRANSIT / DRIVE / WALK)",
            default=state.get("travel_mode", "TRANSIT"),
        ).upper()
    if mode not in ("TRANSIT", "DRIVE", "WALK"):
        die(f"'{mode}' is not TRANSIT, DRIVE, or WALK. Re-run.")
    state["travel_mode"] = mode
    success(f"default travel mode: {mode}")


@step("Grant Cloud Run runtime SA access to secrets")
def step_grant_iam(state, args):
    pid = state["project_id"]
    pnum = state["project_number"]
    sa = f"{pnum}-compute@developer.gserviceaccount.com"

    for name in SECRET_NAMES:
        subprocess.run(
            [
                "gcloud", "secrets", "add-iam-policy-binding", name,
                f"--member=serviceAccount:{sa}",
                "--role=roles/secretmanager.secretAccessor",
                f"--project={pid}",
                "--condition=None",
            ],
            check=True, capture_output=True,
        )
    success(f"granted secretAccessor on {len(SECRET_NAMES)} secrets to {sa}")


@step("Create OAuth-state bucket")
def step_oauth_state_bucket(state, args):
    """GCS bucket persisting FastMCP's OAuth state across instance restarts.

    Without it every Cloud Run cold start / deploy wipes the in-container
    token store and MCP clients must re-authenticate. Mounted into the
    service via a Cloud Storage volume; FASTMCP_HOME points at the mount.
    """
    pid = state["project_id"]
    bucket = f"{pid}-oauth-state"
    state["oauth_state_bucket"] = bucket

    check = subprocess.run(
        ["gcloud", "storage", "buckets", "describe", f"gs://{bucket}",
         f"--project={pid}"],
        capture_output=True,
    )
    if check.returncode == 0:
        success(f"bucket gs://{bucket} already exists")
        return

    gcloud([
        "storage", "buckets", "create", f"gs://{bucket}",
        f"--project={pid}", f"--location={state['region']}",
        "--uniform-bucket-level-access",
    ])
    sa = f"{state['project_number']}-compute@developer.gserviceaccount.com"
    gcloud([
        "storage", "buckets", "add-iam-policy-binding", f"gs://{bucket}",
        f"--member=serviceAccount:{sa}",
        "--role=roles/storage.objectAdmin",
    ])
    success(f"created gs://{bucket}, granted objectAdmin to runtime SA")


@step("Deploy to Cloud Run")
def step_deploy(state, args):
    pid = state["project_id"]
    region = state["region"]
    service = state["service_name"]
    base_url = state["mcp_base_url"]
    bucket = state.get("oauth_state_bucket", f"{pid}-oauth-state")

    info("Building image with Cloud Build and rolling out (~3-5 min)...")
    info(
        "💰 The image (~1.4 GB, includes headless Chromium) exceeds Artifact "
        "Registry's free 0.5 GB → ~$0.10/month."
    )
    cmd = [
        "gcloud", "run", "deploy", service,
        f"--project={pid}",
        f"--region={region}",
        "--source=.",
        "--allow-unauthenticated",
        "--port=8080",
        # get_events runs headless Chromium in-container: it needs the
        # memory bump, and low concurrency keeps simultaneous browsers off one
        # instance (the agent fans out one call per venue website).
        "--memory=2Gi",
        "--cpu=2",
        "--timeout=300",
        "--concurrency=4",
        # Single instance: OAuth session state lives in the GCS-fuse bucket,
        # which lacks instant cross-instance read-after-write consistency.
        # Multiple instances → some /mcp calls 401 → connector auth loops.
        # One instance owns all state; fine for a personal single-user server.
        "--max-instances=1",
        "--update-secrets=" + ",".join(f"{n}={n}:latest" for n in SECRET_NAMES),
        # Persist OAuth state (client registrations, refresh tokens) so
        # sessions survive restarts; FASTMCP_HOME points at the GCS mount.
        f"--add-volume=name=oauth-state,type=cloud-storage,bucket={bucket}",
        "--add-volume-mount=volume=oauth-state,mount-path=/mnt/oauth-state",
        f"--set-env-vars=MCP_BASE_URL={base_url},FASTMCP_HOME=/mnt/oauth-state,"
        f"CONNECTOR_LANGUAGE={state.get('language', 'en')},"
        f"DEFAULT_TRAVEL_MODE={state.get('travel_mode', 'TRANSIT')}",
    ]
    _log_cmd(cmd)
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        die("Cloud Run deploy failed. Re-run installer to retry.")
    state["deployed"] = True
    success(f"deployed: {base_url}")


@step("Smoke-test deployed service")
def step_smoke(state, args):
    url = state["mcp_base_url"] + "/mcp"
    req = urllib.request.Request(
        url, method="POST",
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        warn("Got 200 (expected 401). Auth might not be wired correctly.")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            success("/mcp returns 401 unauthenticated — auth wired correctly")
        else:
            warn(f"unexpected HTTP {e.code}")
    except urllib.error.URLError as e:
        warn(f"could not reach service: {e}")


# ---------- Preflight manifest ----------


def print_manifest(args) -> None:
    """Everything the installer creates, the manual steps, and the money —
    on one screen. Real risks and decision points only."""
    print(color("  What gets created (in YOUR GCP project)", Colors.BOLD))
    print(
        f"    {len(REQUIRED_APIS)} APIs enabled · 2 restricted API keys "
        f"(Maps, Gemini) · {len(SECRET_NAMES)} secrets\n"
        f"    OAuth-state bucket · Cloud Run service '{args.service_name}' "
        f"({args.region})"
    )
    print()
    print(color("  What YOU do in a browser (Google has no API for these)", Colors.BOLD))
    print(
        "    1. Link a billing account (if not already linked)\n"
        "    2. OAuth consent screen + client — ~4 min, guided\n"
        "    Everything else (keys, secrets, deploy) is automated."
    )
    print()
    print(color("  💰 What can cost money", Colors.BOLD))
    print(
        "    • Gemini (event scraping) — THE DECISION THAT MATTERS:\n"
        "      free tier = 20 requests/day ≈ 1-2 event searches, then errors.\n"
        "      With billing on the key: ~$0.05-0.15 per event search.\n"
        "    • Container image (~1.4 GB) exceeds Artifact Registry's free\n"
        "      0.5 GB → ~$0.10/month.\n"
        "    • Maps searches & routing — free monthly caps cover personal use.\n"
        "    • Cloud Run / Build / secrets / bucket — free tier at this scale."
    )
    print()


# ---------- Main ----------


def main():
    parser = argparse.ArgumentParser(
        description="Personal Google Maps MCP installer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "After install, the printed URL is your MCP endpoint. Add it as a custom\n"
            "connector in Claude Mobile, Claude Desktop, ChatGPT, or any MCP client.\n"
            "Sign in with one of the allowed emails to complete the OAuth flow.\n\n"
            "To start over from scratch: python install.py --reset\n"
            "To uninstall everything:   python uninstall.py\n"
        ),
    )
    parser.add_argument(
        "--project-id",
        help="GCP project ID to use or create (default: pick interactively)",
    )
    parser.add_argument(
        "--region", default=DEFAULT_REGION,
        help=f"Cloud Run region (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--service-name", default=DEFAULT_SERVICE_NAME,
        help=f"Cloud Run service name (default: {DEFAULT_SERVICE_NAME})",
    )
    parser.add_argument(
        "--allowed-emails",
        help="Comma-separated emails allowed to authenticate (default: prompt)",
    )
    parser.add_argument(
        "--language",
        help="BCP-47 code all results are returned in (default: prompt, 'en')",
    )
    parser.add_argument(
        "--travel-mode",
        help="Default get_route mode: TRANSIT, DRIVE, or WALK (default: prompt)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Discard saved state and start over",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be installed (and what it costs), then exit",
    )
    args = parser.parse_args()

    if args.reset and STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"State reset ({STATE_PATH} removed).")

    state = load_state()

    print()
    print(color("Google Maps MCP installer", Colors.BOLD))
    print(
        color(
            "Provisions a private MCP endpoint in your own GCP account.",
            Colors.DIM,
        )
    )
    print(color(f"State file: {STATE_PATH}", Colors.DIM))
    print(color(f"Logs:       {LOG_PATH}", Colors.DIM))
    print()

    fresh_install = not any(k.startswith("_step_") for k in state)
    if args.dry_run or fresh_install:
        print_manifest(args)
        if args.dry_run:
            sys.exit(0)
        if not confirm("Proceed?", default=True):
            sys.exit(0)
        print()

    total = len(STEPS)
    for i, (title, fn) in enumerate(STEPS, 1):
        flag = f"_step_{fn.__name__}_done"
        header = color(f"[{i}/{total}]", Colors.BOLD)
        print(f"{header} {title}")
        if state.get(flag):
            info("(already done — re-run with --reset to redo)")
            print()
            continue
        try:
            fn(state, args)
            state[flag] = True
            save_state(state)
        except KeyboardInterrupt:
            print("\n  Interrupted. Re-run to resume from here.")
            sys.exit(130)
        except GcloudError as e:
            error(str(e))
            print(
                color(
                    f"  Saved state to {STATE_PATH}. Re-run to retry from this step.",
                    Colors.DIM,
                )
            )
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            error(f"unexpected error: {e}")
            sys.exit(1)
        print()

    base_url = state.get("mcp_base_url", "")
    print(color("=" * 64, Colors.GREEN))
    print(color("  Done!", Colors.BOLD + Colors.GREEN))
    print(color("=" * 64, Colors.GREEN))
    print(f"  MCP endpoint: {color(base_url + '/mcp', Colors.BOLD)}")
    print()
    print("  Add this URL as a custom MCP connector in your client of choice:")
    print("    • Claude Mobile / Desktop / Web — Settings → Connectors")
    print("    • ChatGPT (when MCP custom connectors land)")
    print("    • MCP Inspector — Streamable HTTP transport")
    print()
    print("  When prompted, sign in with one of these allowed emails:")
    print(f"    {state.get('allowed_emails', '(see Secret Manager)')}")
    print()
    print(
        "  💰 Standing cost ≈ $0.10/month. Event searches bill Gemini usage "
        "(~$0.05-0.15 each\n     with billing enabled on the key; without it, "
        "1-2 free searches/day)."
    )
    print()
    print(color("  To uninstall: python uninstall.py", Colors.DIM))
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
