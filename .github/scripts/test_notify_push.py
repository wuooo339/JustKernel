"""Exercise real mail construction and mocked TLS delivery without credentials."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import notify_push as notify


# ---- isolated push and SMTP protocol fixtures ------------------------------
class MailTests(unittest.TestCase):
    def setUp(self):
        self.event = {
            "repository": {"full_name": "wuooo339/JustKernel", "default_branch": "main"},
            "workflow_run": {
                "id": 123,
                "event": "push",
                "run_attempt": 1,
                "head_repository": {"full_name": "wuooo339/JustKernel"},
                "head_branch": "refactor",
                "head_sha": "a" * 40,
                "conclusion": "failure",
                "html_url": "https://github.com/wuooo339/JustKernel/actions/runs/123",
                "head_commit": {
                    "author": {"name": "Fixture"},
                    "message": "Fix parser\nLiteral $(cmd)",
                },
            },
        }
        self.env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USERNAME": "sender@example.com",
            "SMTP_PASSWORD": "test-fixture-not-a-real-password",
        }

    def test_only_first_attempt_repository_pushes_or_manual_test_are_eligible(self):
        self.assertTrue(notify.eligible(self.event, "workflow_run"))
        self.assertTrue(notify.eligible(self.event, "workflow_dispatch"))
        self.assertFalse(notify.eligible(self.event, "workflow_run", "2"))
        self.event["workflow_run"]["run_attempt"] = 2
        self.assertFalse(notify.eligible(self.event, "workflow_run"))
        self.event["workflow_run"].update(run_attempt=1, event="pull_request")
        self.assertFalse(notify.eligible(self.event, "workflow_run"))
        self.event["workflow_run"].update(event="push", head_repository={"full_name": "fork/repo"})
        self.assertFalse(notify.eligible(self.event, "workflow_run"))

    def test_default_recipient_and_complete_plain_text_report(self):
        config, missing = notify.configuration(self.env)
        self.assertFalse(missing)
        self.assertEqual(config.recipients, ("gresces@foxmail.com",))
        mail = notify.message(self.event, "workflow_run", config, ["- Linux: failure"])
        self.assertIn("refactor aaaaaaaa", mail["Subject"])
        self.assertEqual(mail["To"], "gresces@foxmail.com")
        self.assertIn("actions/runs/123", mail.get_content())
        self.assertIn("Literal $(cmd)", mail.get_content())
        self.assertIn("- Linux: failure", mail.get_content())
        self.assertNotIn(config.password, mail.as_string())
        self.assertEqual(mail.get_content_type(), "text/plain")

    def test_recipient_override_and_address_injection_validation(self):
        config, _ = notify.configuration({**self.env, "NOTIFY_EMAIL": "guoyangfan2003@outlook.com"})
        self.assertEqual(config.recipients, ("guoyangfan2003@outlook.com",))
        with self.assertRaises(ValueError):
            notify.configuration({**self.env, "NOTIFY_EMAIL": "x@example.com\nBcc: z@example.com"})

    def test_tls_is_required_and_starttls_authenticates_after_upgrade(self):
        with self.assertRaises(ValueError):
            notify.configuration({**self.env, "SMTP_SECURITY": "none"})
        for security, constructor in (("ssl", "SMTP_SSL"), ("starttls", "SMTP")):
            with self.subTest(security=security):
                config, _ = notify.configuration({**self.env, "SMTP_SECURITY": security})
                client = MagicMock()
                client.send_message.return_value = {}
                with patch.object(notify.smtplib, constructor) as smtp:
                    smtp.return_value.__enter__.return_value = client
                    notify.deliver(config, notify.message(self.event, "workflow_run", config))
                client.login.assert_called_once_with(config.username, config.password)
                client.send_message.assert_called_once()
                self.assertEqual(client.starttls.call_count, int(security == "starttls"))
                if security == "starttls":
                    methods = [call[0] for call in client.method_calls]
                    self.assertLess(methods.index("starttls"), methods.index("login"))

    def test_missing_configuration_is_explicit_and_never_sends(self):
        with tempfile.TemporaryDirectory() as folder:
            event = Path(folder) / "event.json"
            report = Path(folder) / "summary.md"
            event.write_text(json.dumps(self.event), encoding="utf-8")
            env = {
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_EVENT_NAME": "workflow_run",
                "GITHUB_STEP_SUMMARY": str(report),
            }
            with patch.object(notify, "deliver") as send, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(notify.main(env), 0)
            send.assert_not_called()
            self.assertIn("No email was sent", report.read_text(encoding="utf-8"))

    def test_mail_failure_is_reported_without_leaking_secret_or_retrying(self):
        with tempfile.TemporaryDirectory() as folder:
            event = Path(folder) / "event.json"
            event.write_text(json.dumps(self.event), encoding="utf-8")
            env = {**self.env, "GITHUB_EVENT_PATH": str(event), "GITHUB_EVENT_NAME": "workflow_run"}
            output = io.StringIO()
            with (
                patch.object(notify, "job_summary", return_value=[]),
                patch.object(
                    notify, "deliver", side_effect=RuntimeError(self.env["SMTP_PASSWORD"])
                ) as send,
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(notify.main(env), 1)
            send.assert_called_once()
            self.assertNotIn(self.env["SMTP_PASSWORD"], output.getvalue())
            self.assertIn("RuntimeError", output.getvalue())


if __name__ == "__main__":
    unittest.main()
