"""
Tests for core/slack_client.py.

Covers both notification methods, Block Kit structure, and webhook failure handling.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.slack_client import SlackClient


DRIFT_SUMMARY = {
    "resources_to_add": ["aws_s3_bucket.logs"],
    "resources_to_change": ["aws_instance.app"],
    "resources_to_destroy": [],
}

RISK_DATA = {
    "risk_score": 85,
    "risk_level": "HIGH",
    "reasoning": "Security group opened to 0.0.0.0/0 on port 22.",
    "recommended_action": "ESCALATE",
    "dangerous_patterns": ["0.0.0.0/0"],
    "security_impact": "SSH port exposed to the internet.",
}

AUDIT_LOGS = [
    {
        "event_time": "2024-06-01 12:00:00 UTC",
        "username": "arn:aws:iam::123456789:user/john.doe",
        "event_name": "AuthorizeSecurityGroupIngress",
        "resource_name": "aws_security_group.app",
        "source_ip": "198.51.100.42",
    }
]


def _mock_post(status_code: int = 200) -> MagicMock:
    """Return a mock requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    return mock_resp


class TestSendAutoRemediationNotice:
    """Tests for SlackClient.send_auto_remediation_notice."""

    def test_returns_true_on_200(self):
        """Returns True when webhook responds with 200."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        with patch("core.slack_client.requests.post", return_value=_mock_post(200)):
            result = client.send_auto_remediation_notice(DRIFT_SUMMARY, "Apply complete!")
        assert result is True

    def test_returns_false_on_non_200(self):
        """Returns False when webhook responds with a non-200 status."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        with patch("core.slack_client.requests.post", return_value=_mock_post(500)):
            result = client.send_auto_remediation_notice(DRIFT_SUMMARY, "Apply failed.")
        assert result is False

    def test_returns_false_when_no_webhook(self):
        """Returns False immediately when no webhook URL is configured."""
        client = SlackClient(webhook_url="")
        result = client.send_auto_remediation_notice(DRIFT_SUMMARY, "output")
        assert result is False

    def test_payload_has_green_color(self):
        """The attachment color is green for auto-remediation notices."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        captured = {}

        def capture_post(url, data, headers, timeout):
            captured["payload"] = json.loads(data)
            return _mock_post(200)

        with patch("core.slack_client.requests.post", side_effect=capture_post):
            client.send_auto_remediation_notice(DRIFT_SUMMARY, "apply output")

        color = captured["payload"]["attachments"][0]["color"]
        assert color == "#36a64f"

    def test_payload_contains_resource_names(self):
        """The Block Kit blocks mention the drifted resource names."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        captured = {}

        def capture_post(url, data, headers, timeout):
            captured["payload"] = json.loads(data)
            return _mock_post(200)

        with patch("core.slack_client.requests.post", side_effect=capture_post):
            client.send_auto_remediation_notice(DRIFT_SUMMARY, "done")

        blocks_text = json.dumps(captured["payload"])
        assert "aws_s3_bucket.logs" in blocks_text
        assert "aws_instance.app" in blocks_text


class TestSendEscalationAlert:
    """Tests for SlackClient.send_escalation_alert."""

    def test_returns_true_on_200(self):
        """Returns True when webhook responds with 200."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        with patch("core.slack_client.requests.post", return_value=_mock_post(200)):
            result = client.send_escalation_alert(
                RISK_DATA, DRIFT_SUMMARY, AUDIT_LOGS, "2024-06-01T12:00:00Z"
            )
        assert result is True

    def test_payload_has_red_color(self):
        """The attachment color is red for escalation alerts."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        captured = {}

        def capture_post(url, data, headers, timeout):
            captured["payload"] = json.loads(data)
            return _mock_post(200)

        with patch("core.slack_client.requests.post", side_effect=capture_post):
            client.send_escalation_alert(
                RISK_DATA, DRIFT_SUMMARY, AUDIT_LOGS, "2024-06-01T12:00:00Z"
            )

        color = captured["payload"]["attachments"][0]["color"]
        assert color == "#cc0000"

    def test_payload_contains_risk_score(self):
        """The payload includes the risk score and risk level."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        captured = {}

        def capture_post(url, data, headers, timeout):
            captured["payload"] = json.loads(data)
            return _mock_post(200)

        with patch("core.slack_client.requests.post", side_effect=capture_post):
            client.send_escalation_alert(
                RISK_DATA, DRIFT_SUMMARY, AUDIT_LOGS, "2024-06-01T12:00:00Z"
            )

        blocks_text = json.dumps(captured["payload"])
        assert "85" in blocks_text
        assert "HIGH" in blocks_text

    def test_payload_contains_audit_log_actor(self):
        """CloudTrail actor appears in the escalation payload."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        captured = {}

        def capture_post(url, data, headers, timeout):
            captured["payload"] = json.loads(data)
            return _mock_post(200)

        with patch("core.slack_client.requests.post", side_effect=capture_post):
            client.send_escalation_alert(
                RISK_DATA, DRIFT_SUMMARY, AUDIT_LOGS, "2024-06-01T12:00:00Z"
            )

        blocks_text = json.dumps(captured["payload"])
        assert "john.doe" in blocks_text

    def test_payload_has_dividers_between_sections(self):
        """Block Kit dividers are present to separate sections."""
        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        captured = {}

        def capture_post(url, data, headers, timeout):
            captured["payload"] = json.loads(data)
            return _mock_post(200)

        with patch("core.slack_client.requests.post", side_effect=capture_post):
            client.send_escalation_alert(
                RISK_DATA, DRIFT_SUMMARY, AUDIT_LOGS, "2024-06-01T12:00:00Z"
            )

        blocks = captured["payload"]["attachments"][0]["blocks"]
        divider_count = sum(1 for b in blocks if b.get("type") == "divider")
        assert divider_count >= 3

    def test_network_error_returns_false(self):
        """Returns False when requests.post raises an exception."""
        import requests as req_lib

        client = SlackClient(webhook_url="https://hooks.slack.com/test")
        with patch(
            "core.slack_client.requests.post",
            side_effect=req_lib.RequestException("connection refused"),
        ):
            result = client.send_escalation_alert(
                RISK_DATA, DRIFT_SUMMARY, AUDIT_LOGS, "now"
            )
        assert result is False
