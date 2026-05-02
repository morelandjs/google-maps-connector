#!/usr/bin/env python3
"""Companion uninstaller for the Google Maps MCP installer.

Tears down the resources install.py created. Each resource is confirmed
individually unless `--yes` is passed. The OAuth Client + consent screen
require manual deletion — this script prints exact click-paths for those.

Usage:
    python uninstall.py
    python uninstall.py --yes              # skip per-resource confirmations
    python uninstall.py --delete-project   # nuke the entire GCP project
                                           # (single operation; supersedes the rest)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Reuse helpers from install.py (lives next to this file).
from install import (
    Colors,
    GcloudError,
    SECRET_NAMES,
    STATE_PATH,
    color,
    confirm,
    die,
    error,
    gcloud,
    info,
    load_state,
    success,
    warn,
)


def confirm_or_skip(question: str, *, default: bool, auto_yes: bool) -> bool:
    if auto_yes:
        info(f"{question} → yes (--yes)")
        return True
    return confirm(question, default=default)


def delete_cloud_run(state: dict, *, auto_yes: bool) -> None:
    pid = state.get("project_id")
    region = state.get("region")
    service = state.get("service_name")
    if not (pid and region and service):
        warn("Cloud Run service info missing from state; skipping")
        return

    # Confirm exists
    check = subprocess.run(
        [
            "gcloud", "run", "services", "describe", service,
            f"--region={region}", f"--project={pid}",
        ],
        capture_output=True,
    )
    if check.returncode != 0:
        info(f"Cloud Run service '{service}' not found in {region}; skipping")
        return

    if confirm_or_skip(
        f"Delete Cloud Run service {service!r} in {region}?",
        default=True, auto_yes=auto_yes,
    ):
        try:
            gcloud(
                [
                    "run", "services", "delete", service,
                    f"--region={region}", f"--project={pid}", "--quiet",
                ],
                capture=False,
            )
            success(f"deleted Cloud Run service {service}")
        except GcloudError as e:
            error(str(e))


def delete_secrets(state: dict, *, auto_yes: bool) -> None:
    pid = state.get("project_id")
    if not pid:
        warn("project_id missing; skipping secrets")
        return

    existing = []
    for name in SECRET_NAMES:
        check = subprocess.run(
            ["gcloud", "secrets", "describe", name, f"--project={pid}"],
            capture_output=True,
        )
        if check.returncode == 0:
            existing.append(name)

    if not existing:
        info("No secrets to delete (all already absent)")
        return

    info(f"Found {len(existing)} secret(s) to delete:")
    for n in existing:
        print(f"      - {n}")
    if not confirm_or_skip(
        "Delete all of them?", default=True, auto_yes=auto_yes,
    ):
        return

    for name in existing:
        try:
            gcloud(
                ["secrets", "delete", name, f"--project={pid}", "--quiet"]
            )
            success(f"deleted secret {name}")
        except GcloudError as e:
            error(str(e))


def delete_api_key(state: dict, *, auto_yes: bool) -> None:
    name = state.get("maps_api_key_name")
    pid = state.get("project_id")
    if not (name and pid):
        # Fallback: search by display name in case state lost track
        if pid:
            list_out = gcloud(
                [
                    "services", "api-keys", "list",
                    "--filter=displayName=Google Maps MCP",
                    f"--project={pid}",
                    "--format=value(name)",
                ]
            )
            keys = [k for k in list_out.strip().splitlines() if k]
            if not keys:
                info("No Maps API key with display name 'Google Maps MCP' found")
                return
            name = keys[0]
        else:
            warn("project_id and api key name both missing; skipping")
            return

    if confirm_or_skip(
        f"Delete Google Maps API key ({name.split('/')[-1]})?",
        default=True, auto_yes=auto_yes,
    ):
        try:
            gcloud(
                ["services", "api-keys", "delete", name, "--quiet"],
                capture=False,
            )
            success("deleted API key")
        except GcloudError as e:
            error(str(e))


def delete_artifact_registry(state: dict, *, auto_yes: bool) -> None:
    """Cloud Run created a 'cloud-run-source-deploy' Artifact Registry repo
    on first deploy. It holds image layers; ~$0.10/month. Optional cleanup."""
    pid = state.get("project_id")
    region = state.get("region")
    if not (pid and region):
        return

    repo = "cloud-run-source-deploy"
    check = subprocess.run(
        [
            "gcloud", "artifacts", "repositories", "describe", repo,
            f"--location={region}", f"--project={pid}",
        ],
        capture_output=True,
    )
    if check.returncode != 0:
        info(f"Artifact Registry repo '{repo}' not found; skipping")
        return

    if not confirm_or_skip(
        f"Delete Artifact Registry repo '{repo}' in {region}? "
        "(stores built container images, ~$0.10/mo if left)",
        default=True, auto_yes=auto_yes,
    ):
        return

    try:
        gcloud(
            [
                "artifacts", "repositories", "delete", repo,
                f"--location={region}", f"--project={pid}", "--quiet",
            ],
            capture=False,
        )
        success(f"deleted Artifact Registry repo {repo}")
    except GcloudError as e:
        error(str(e))


def delete_project(state: dict, *, auto_yes: bool) -> None:
    pid = state.get("project_id")
    if not pid:
        die("Cannot delete project: project_id missing from state")

    print()
    warn(f"You are about to DELETE the entire GCP project '{pid}'.")
    warn("This removes EVERYTHING in the project — including resources NOT")
    warn("created by this installer. The deletion is reversible for 30 days.")
    print()

    if not auto_yes:
        typed = input(f"  Type the project ID exactly to confirm: ").strip()
        if typed != pid:
            die("Project ID did not match. Aborted.")

    try:
        gcloud(["projects", "delete", pid, "--quiet"], capture=False)
        success(f"project {pid} scheduled for deletion (recoverable for 30 days)")
    except GcloudError as e:
        error(str(e))


def print_manual_cleanup(state: dict) -> None:
    """OAuth Client + consent screen are web-console-only deletes."""
    pid = state.get("project_id")
    if not pid:
        return

    print()
    print(color("Manual cleanup (web console only):", Colors.BOLD))
    print()
    print("  • Delete the OAuth 2.0 Client ID:")
    print(
        f"    https://console.cloud.google.com/apis/credentials?project={pid}"
    )
    print("    Find 'Google Maps MCP Server', click the trash icon.")
    print()
    print("  • Reset / delete the OAuth consent screen (optional):")
    print(
        f"    https://console.cloud.google.com/apis/credentials/consent?project={pid}"
    )
    print("    Click 'Delete' or revert configuration.")
    print()


def maybe_remove_state(*, auto_yes: bool) -> None:
    if not STATE_PATH.exists():
        return
    if confirm_or_skip(
        f"Remove installer state file at {STATE_PATH}?",
        default=True, auto_yes=auto_yes,
    ):
        STATE_PATH.unlink()
        success(f"removed {STATE_PATH}")


def main():
    parser = argparse.ArgumentParser(
        description="Tear down resources created by install.py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "By default, this deletes the Cloud Run service, secrets, Maps API\n"
            "key, and Artifact Registry repo — but leaves the GCP project intact.\n"
            "Pass --delete-project to also delete the project (single, broader op).\n\n"
            "OAuth Client + consent screen require web-console deletion; URLs are\n"
            "printed at the end.\n"
        ),
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="skip per-resource confirmation prompts",
    )
    parser.add_argument(
        "--delete-project", action="store_true",
        help="delete the entire GCP project (skips per-resource cleanup)",
    )
    parser.add_argument(
        "--project-id",
        help="override project ID from state file (advanced)",
    )
    args = parser.parse_args()

    state = load_state()
    if args.project_id:
        state["project_id"] = args.project_id

    if not state.get("project_id"):
        die(
            "No state file and no --project-id given. Either run install.py "
            "first, or pass --project-id <id> to clean up a specific project."
        )

    print()
    print(color("Google Maps MCP uninstaller", Colors.BOLD))
    print(color(f"Project: {state['project_id']}", Colors.DIM))
    print()

    if args.delete_project:
        delete_project(state, auto_yes=args.yes)
        maybe_remove_state(auto_yes=args.yes)
        print()
        print(color("All done.", Colors.GREEN))
        return

    print(color("Will delete:", Colors.BOLD))
    print(
        f"  • Cloud Run service   '{state.get('service_name', '?')}' "
        f"in {state.get('region', '?')}"
    )
    print(f"  • {len(SECRET_NAMES)} secrets in Secret Manager")
    print("  • Maps API key (Google Maps MCP)")
    print("  • Artifact Registry repo 'cloud-run-source-deploy' (optional)")
    print()

    if not confirm_or_skip("Proceed?", default=True, auto_yes=args.yes):
        info("Aborted.")
        sys.exit(0)

    print()
    print(color("Deleting Cloud Run service...", Colors.BOLD))
    delete_cloud_run(state, auto_yes=args.yes)

    print()
    print(color("Deleting secrets...", Colors.BOLD))
    delete_secrets(state, auto_yes=args.yes)

    print()
    print(color("Deleting Maps API key...", Colors.BOLD))
    delete_api_key(state, auto_yes=args.yes)

    print()
    print(color("Deleting Artifact Registry repo...", Colors.BOLD))
    delete_artifact_registry(state, auto_yes=args.yes)

    print_manual_cleanup(state)

    maybe_remove_state(auto_yes=args.yes)

    print()
    print(color("All done.", Colors.GREEN))
    print(
        color(
            "Re-run python install.py to provision again.",
            Colors.DIM,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
