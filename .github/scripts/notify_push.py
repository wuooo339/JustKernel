"""Email one push/checks summary through an explicitly configured SMTP account."""

import json
import os
import re
import smtplib
import ssl
import sys
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path


# ---- configuration ---------------------------------------------------------
@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    security: str
    username: str
    password: str
    sender: str
    recipients: tuple[str, ...]


# ---- validated mail addresses, never shell interpolation --------------------
def addresses(value):
    result = tuple(part.strip() for part in value.split(",") if part.strip())
    if not result or any(
        not re.fullmatch(r"[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+", item) for item in result
    ):
        raise ValueError("Use valid comma-separated email addresses.")
    return result


# ---- configuration is supplied only by Actions variables and secrets --------
def configuration(env):
    required = ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        return None, missing
    security = env.get("SMTP_SECURITY", "ssl") or "ssl"
    if security not in {"ssl", "starttls"}:
        raise ValueError("SMTP_SECURITY must be ssl or starttls; plaintext is disabled.")
    port = int(env.get("SMTP_PORT", "465") or "465")
    if not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT must be between 1 and 65535.")
    sender = env.get("SMTP_FROM") or env["SMTP_USERNAME"]
    addresses(sender)
    return MailConfig(
        env["SMTP_HOST"].strip(),
        port,
        security,
        env["SMTP_USERNAME"],
        env["SMTP_PASSWORD"],
        sender,
        addresses(env.get("NOTIFY_EMAIL") or "gresces@foxmail.com"),
    ), []


# ---- only real repository pushes or an explicit manual smoke test -----------
def eligible(event, event_name, attempt="1"):
    if str(attempt) != "1":
        return False
    if event_name == "workflow_dispatch":
        return True
    run = event.get("workflow_run", {})
    repository = event.get("repository", {}).get("full_name")
    return (
        event_name == "workflow_run"
        and run.get("event") == "push"
        and run.get("run_attempt", 1) == 1
        and bool(repository)
        and run.get("head_repository", {}).get("full_name") == repository
    )


# ---- optional public execution detail; no branch code/artifacts are loaded ---
def job_summary(event, env):
    run = event.get("workflow_run", {})
    if not run.get("id"):
        return []
    repository = event["repository"]["full_name"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository name.")
    run_id = int(run["id"])
    endpoint = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"
    headers = {"User-Agent": "JustKernel-push-email", "Accept": "application/vnd.github+json"}
    if env.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + env["GITHUB_TOKEN"]
    request = urllib.request.Request(endpoint, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        jobs = json.load(response)["jobs"]
    lines = []
    for job in jobs:
        lines.append(f"- {job['name']}: {job.get('conclusion') or job['status']}")
        for step in job.get("steps", []):
            if step.get("conclusion") == "failure":
                lines.append(f"  Failed step: {step['name']}")
    return lines


# ---- untrusted commit messages appear only in the plain-text mail body -------
def message(event, event_name, config, jobs=()):
    repository = event["repository"]["full_name"]
    run = event.get("workflow_run", {})
    commit = run.get("head_commit") or {}
    sha = run.get("head_sha") or "manual-test"
    branch = run.get("head_branch") or event["repository"].get("default_branch", "main")
    status = run.get("conclusion") or "manual-test"
    subject = re.sub(r"[\r\n]+", " ", f"[{repository}] {branch} {sha[:8]} — {status}")
    author = (commit.get("author") or {}).get("name") or "unknown"
    commit_url = f"https://github.com/{repository}/commit/{sha}"
    report_url = run.get("html_url") or f"https://github.com/{repository}/actions"
    body = [
        "JustKernel commit notification",
        "",
        f"Repository: {repository}",
        f"Branch: {branch}",
        f"Commit: {sha}",
        f"Author: {author}",
        f"Checks: {status}",
        f"Commit URL: {commit_url}",
        f"Checks URL: {report_url}",
        "",
        "Commit message:",
        (commit.get("message") or "Manual email delivery test.")[:16000],
    ]
    if jobs:
        body += ["", "Checks by platform:", *jobs]
    mail = EmailMessage()
    mail["Subject"] = subject
    mail["From"] = config.sender
    mail["To"] = ", ".join(config.recipients)
    mail.set_content("\n".join(body) + "\n")
    return mail


# ---- authenticate over TLS; delivery is attempted once, never blindly retried -
def deliver(config, mail):
    context = ssl.create_default_context()
    if config.security == "ssl":
        connection = smtplib.SMTP_SSL(config.host, config.port, timeout=30, context=context)
    else:
        connection = smtplib.SMTP(config.host, config.port, timeout=30)
    with connection as client:
        if config.security == "starttls":
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(config.username, config.password)
        refused = client.send_message(mail)
        if refused:
            raise RuntimeError("Some recipients were rejected by the mail service.")


# ---- a visible setup/delivery summary without credentials or message dumps ---
def summary(env, text):
    if env.get("GITHUB_STEP_SUMMARY"):
        with Path(env["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
            output.write("## Commit email notification\n\n" + text + "\n")


# ---- entrypoint ------------------------------------------------------------
def main(env=None):
    env = os.environ if env is None else env
    try:
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        event_name = env["GITHUB_EVENT_NAME"]
        if not eligible(event, event_name, env.get("GITHUB_RUN_ATTEMPT", "1")):
            summary(env, "Skipped: this is not a first-attempt repository push or manual test.")
            return 0
        config, missing = configuration(env)
        if missing:
            note = "Waiting for SMTP configuration: " + ", ".join(missing)
            print("::notice::" + note)
            summary(env, note + ". No email was sent. See .github/EMAIL_NOTIFICATIONS.md.")
            return 0
        try:
            jobs = job_summary(event, env)
        except (OSError, ValueError, KeyError):
            jobs = ["Platform details unavailable; use the Checks URL for the full result."]
        mail = message(event, event_name, config, jobs)
        deliver(config, mail)
        summary(env, "Mail service accepted the notification for: " + ", ".join(config.recipients))
        print("Notification accepted by the SMTP service.")
        return 0
    except Exception as error:
        # Provider exceptions can contain connection/authentication data. Print
        # only a class/code, never secret values, full events or model content.
        code = getattr(error, "smtp_code", None)
        text = f"Email delivery failed: {type(error).__name__}" + (f" ({code})" if code else "")
        print("::error::" + text)
        summary(env, text + ". Check SMTP settings; delivery was not automatically retried.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
