#!/usr/bin/env python
# scripts/alert_dispatcher.py
"""
Sprint 5 CI/CD & Workflow Alert Dispatcher.

Handles failure notifications when GitHub Actions workflows fail:
1. Formats structured notifications with workflow run metadata, exit codes, and error traces.
2. Sanitizes sensitive secrets, passwords, Bearer tokens, and connection strings from payloads.
3. Dispatches alert payloads to configured webhooks (Discord / Slack).
4. If webhook is not configured or fails, falls back to creating an issue in the GitHub repository
   using GITHUB_TOKEN, with deduplication to prevent issue flooding.

Usage:
    python scripts/alert_dispatcher.py --status failure --workflow "Monthly Archival" --run-id "123456"
"""

import os
import re
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alert_dispatcher")

# Secret redaction patterns
REDACTION_PATTERNS = [
    (re.compile(r"postgres(?:ql)?://([^:]+):([^@]+)@", re.IGNORECASE), r"postgres://\1:[REDACTED]@"),
    (re.compile(r"(password\s*[:=]\s*['\"]?)([^'\";\s]+)", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"ar_live_[a-f0-9]{8}_[A-Za-z0-9_\-]+", re.IGNORECASE), r"[REDACTED_API_KEY]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", re.IGNORECASE), r"[REDACTED_JWT]"),
]


def redact_secrets(text: Optional[str]) -> str:
    """Sanitizes passwords, tokens, JWTs, and database URLs from error messages."""
    if not text:
        return "No error details provided."
    sanitized = str(text)
    for pattern, repl in REDACTION_PATTERNS:
        sanitized = pattern.sub(repl, sanitized)
    return sanitized


def format_discord_payload(
    *,
    workflow_name: str,
    run_id: str,
    run_attempt: str,
    status: str,
    error_message: str,
    repository: str,
    server_url: str = "https://github.com",
    summary_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds a rich Discord embed notification."""
    is_failure = status.lower() in ("failure", "failed", "error")
    color = 15158332 if is_failure else 15844367  # Red or Gold
    status_emoji = "🚨" if is_failure else "⚠️"

    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"

    fields: List[Dict[str, Any]] = [
        {"name": "Workflow", "value": workflow_name, "inline": True},
        {"name": "Status", "value": f"{status_emoji} {status.upper()}", "inline": True},
        {"name": "Run Attempt", "value": str(run_attempt), "inline": True},
        {"name": "Repository", "value": repository, "inline": True},
        {"name": "Actions Run", "value": f"[View Run #{run_id}]({run_url})", "inline": True},
    ]

    if summary_data:
        if "days" in summary_data:
            fields.append({"name": "Retention Window", "value": f"{summary_data['days']} days", "inline": True})
        if "rows_archived" in summary_data:
            fields.append({"name": "Rows Archived", "value": str(summary_data["rows_archived"]), "inline": True})
        if "rows_deleted" in summary_data:
            fields.append({"name": "Rows Deleted", "value": str(summary_data["rows_deleted"]), "inline": True})

    clean_error = redact_secrets(error_message)
    if len(clean_error) > 1000:
        clean_error = clean_error[:1000] + "... [truncated]"

    fields.append({"name": "Error Details", "value": f"```\n{clean_error}\n```", "inline": False})

    return {
        "username": "Anime Recommender CI Watchdog",
        "embeds": [
            {
                "title": f"{status_emoji} Workflow Failure: {workflow_name}",
                "description": f"Workflow run **{run_id}** in `{repository}` failed during execution.",
                "url": run_url,
                "color": color,
                "fields": fields,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def format_slack_payload(
    *,
    workflow_name: str,
    run_id: str,
    run_attempt: str,
    status: str,
    error_message: str,
    repository: str,
    server_url: str = "https://github.com",
    summary_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds a Slack blocks notification."""
    is_failure = status.lower() in ("failure", "failed", "error")
    status_emoji = ":x:" if is_failure else ":warning:"
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"

    clean_error = redact_secrets(error_message)
    if len(clean_error) > 1000:
        clean_error = clean_error[:1000] + "... [truncated]"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{status_emoji} Workflow Alert: {workflow_name}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Workflow:*\n{workflow_name}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{status.upper()}"},
                {"type": "mrkdwn", "text": f"*Repository:*\n`{repository}`"},
                {"type": "mrkdwn", "text": f"*Run:*\n<{run_url}|#{run_id} (Attempt {run_attempt})>"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Error Trace:*\n```{clean_error}```",
            },
        },
    ]

    return {"blocks": blocks}


def send_webhook(webhook_url: str, payload: Dict[str, Any], timeout: int = 10) -> bool:
    """Posts payload to Discord or Slack webhook URL."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AnimeRecommender-AlertDispatcher/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status in (200, 204):
                logger.info(f"Successfully posted alert to webhook (HTTP {response.status}).")
                return True
            logger.warning(f"Webhook returned unexpected status: {response.status}")
            return False
    except Exception as exc:
        logger.error(f"Failed to deliver webhook alert: {exc}")
        return False


def create_github_issue_fallback(
    *,
    token: str,
    repository: str,
    workflow_name: str,
    run_id: str,
    status: str,
    error_message: str,
    server_url: str = "https://github.com",
) -> bool:
    """Creates an issue in the repository when webhook delivery fails or is unconfigured."""
    if not token or not repository or "/" not in repository:
        logger.warning("GitHub token or valid repository (owner/repo) not provided; skipping issue creation.")
        return False

    api_url = f"https://api.github.com/repos/{repository}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "AnimeRecommender-AlertDispatcher/1.0",
    }

    # 1. Deduplication check: check if an open alert issue for this workflow exists
    try:
        check_req = urllib.request.Request(
            f"{api_url}?state=open&labels=telemetry-alert",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(check_req, timeout=10) as resp:
            if resp.status == 200:
                open_issues = json.loads(resp.read().decode("utf-8"))
                for issue in open_issues:
                    if workflow_name in issue.get("title", ""):
                        logger.info(
                            f"Open alert issue #{issue['number']} already exists for '{workflow_name}'. Avoiding duplicate."
                        )
                        return True
    except Exception as check_exc:
        logger.debug(f"Issue deduplication check skipped: {check_exc}")

    # 2. Create the issue
    clean_error = redact_secrets(error_message)
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    issue_body = f"""### 🚨 Automated CI Alert: Workflow Failure

- **Workflow**: `{workflow_name}`
- **Run ID**: [{run_id}]({run_url})
- **Status**: `{status.upper()}`
- **Timestamp**: `{datetime.now(timezone.utc).isoformat()}`

#### Error Details
```text
{clean_error}
```

*This issue was automatically opened by `scripts/alert_dispatcher.py` following an unhandled workflow failure.*
"""

    payload = {
        "title": f"[ALERT] {workflow_name} Failure (Run #{run_id})",
        "body": issue_body,
        "labels": ["telemetry-alert", "bug", "automated-issue"],
    }

    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in (200, 201):
                created = json.loads(response.read().decode("utf-8"))
                logger.info(f"Created fallback GitHub issue #{created.get('number')}: {created.get('html_url')}")
                return True
            logger.warning(f"Failed to create GitHub issue: HTTP {response.status}")
            return False
    except Exception as exc:
        logger.error(f"GitHub issue creation failed: {exc}")
        return False


def dispatch_alert(
    *,
    status: str,
    workflow: str,
    run_id: str,
    run_attempt: str = "1",
    error_message: Optional[str] = None,
    summary_file: Optional[str] = None,
    webhook_url: Optional[str] = None,
    github_token: Optional[str] = None,
    repository: Optional[str] = None,
) -> bool:
    """Orchestrates alert delivery via webhook or fallback GitHub issue."""
    repo = repository or os.getenv("GITHUB_REPOSITORY", "org/anime_recommender")
    token = github_token or os.getenv("GITHUB_TOKEN", "")
    webhook = webhook_url or os.getenv("ALERT_WEBHOOK_URL", "")

    summary_data = None
    if summary_file and os.path.exists(summary_file):
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
        except Exception as e:
            logger.debug(f"Could not load summary file: {e}")

    err_text = error_message or ""
    if not err_text and summary_data and "error" in summary_data:
        err_text = str(summary_data["error"])
    if not err_text:
        err_text = f"Workflow '{workflow}' step exited with failure status."

    dispatched = False
    if webhook:
        # Determine Discord vs Slack payload
        if "discord.com" in webhook:
            payload = format_discord_payload(
                workflow_name=workflow,
                run_id=run_id,
                run_attempt=run_attempt,
                status=status,
                error_message=err_text,
                repository=repo,
                summary_data=summary_data,
            )
        else:
            payload = format_slack_payload(
                workflow_name=workflow,
                run_id=run_id,
                run_attempt=run_attempt,
                status=status,
                error_message=err_text,
                repository=repo,
                summary_data=summary_data,
            )
        dispatched = send_webhook(webhook, payload)

    if not dispatched and token:
        logger.info("Webhook dispatch not completed; attempting GitHub issue fallback...")
        dispatched = create_github_issue_fallback(
            token=token,
            repository=repo,
            workflow_name=workflow,
            run_id=run_id,
            status=status,
            error_message=err_text,
        )

    return dispatched


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Workflow Failure Alert Dispatcher")
    parser.add_argument("--status", default="failure", help="Workflow execution status")
    parser.add_argument("--workflow", default="Telemetry Workflow", help="Name of workflow")
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", "0"), help="GitHub Actions run ID")
    parser.add_argument("--run-attempt", default=os.getenv("GITHUB_RUN_ATTEMPT", "1"), help="GitHub Actions run attempt")
    parser.add_argument("--error-message", default=None, help="Explicit error message or stack trace")
    parser.add_argument("--summary-file", default=None, help="Path to archive summary JSON file")
    args = parser.parse_args(argv)

    dispatch_alert(
        status=args.status,
        workflow=args.workflow,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        error_message=args.error_message,
        summary_file=args.summary_file,
    )
    # Always exit 0 so alerting doesn't mask upstream error in CI
    return 0


if __name__ == "__main__":
    sys.exit(main())
