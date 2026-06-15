"""
Tests for agent/graph.py.

Runs the full compiled graph end-to-end with all external I/O mocked.
Covers NO_DRIFT, AUTO_REMEDIATED, ESCALATED, and ERROR final statuses.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.graph import app


def _base_state(terraform_dir: str = "terraform") -> dict:
    return {
        "terraform_dir": terraform_dir,
        "plan_exit_code": -1,
        "plan_output": "",
        "plan_error": "",
        "parsed_drift": {},
        "has_drift": False,
        "risk_score": 0,
        "risk_level": "",
        "risk_reasoning": "",
        "recommended_action": "",
        "affected_resources": [],
        "dangerous_patterns_found": [],
        "auto_apply_success": False,
        "auto_apply_output": "",
        "audit_log_entries": [],
        "slack_sent": False,
        "final_status": "",
        "error_message": "",
        "run_timestamp": "",
    }


LOW_RISK_LLM = """{
    "risk_score": 15, "risk_level": "LOW",
    "reasoning": "Only tag name changes — no security impact.",
    "affected_resources": ["aws_instance.app"],
    "dangerous_patterns": [], "recommended_action": "AUTO_APPLY", "security_impact": ""
}"""

HIGH_RISK_LLM = """{
    "risk_score": 95, "risk_level": "CRITICAL",
    "reasoning": "Security group opened SSH to the world.",
    "affected_resources": ["aws_security_group.app"],
    "dangerous_patterns": ["0.0.0.0/0 on port 22"],
    "recommended_action": "ESCALATE",
    "security_impact": "Remote SSH access exposed globally."
}"""

DRIFT_PLAN = """
Terraform will perform the following actions:
  # aws_instance.app will be updated in-place
  ~ resource "aws_instance" "app" { ~ tags = {} }
Plan: 0 to add, 1 to change, 0 to destroy.
"""

HIGH_RISK_PLAN = """
Terraform will perform the following actions:
  # aws_security_group.app will be updated in-place
  ~ resource "aws_security_group" "app" {
      ~ ingress { ~ cidr_blocks = ["10.0.0.0/8"] -> ["0.0.0.0/0"] }
    }
Plan: 0 to add, 1 to change, 0 to destroy.
"""

PARSED_LOW = {
    "resources_to_add": [], "resources_to_change": ["aws_instance.app"],
    "resources_to_destroy": [], "raw_changes": DRIFT_PLAN,
}
PARSED_HIGH = {
    "resources_to_add": [], "resources_to_change": ["aws_security_group.app"],
    "resources_to_destroy": [], "raw_changes": HIGH_RISK_PLAN,
}
AUDIT_ENTRY = {
    "event_time": "2024-06-01 12:00:00 UTC", "username": "actor",
    "event_name": "AuthorizeSecurityGroupIngress",
    "resource_name": "aws_security_group.app", "source_ip": "1.2.3.4",
}


def _make_tf(plan_result, parsed, apply_result=None):
    m = MagicMock()
    m.run_plan.return_value = plan_result
    m.parse_plan_output.return_value = parsed
    if apply_result:
        m.run_apply.return_value = apply_result
    return m


class TestGraphNoDrift:
    def test_no_drift_path(self):
        tf = _make_tf({"exit_code": 0, "stdout": "No changes.", "stderr": "", "success": True}, {})
        with patch("agent.nodes._get_terraform", return_value=tf):
            final = app.invoke(_base_state())
        assert final["final_status"] == "NO_DRIFT"
        assert final["has_drift"] is False


class TestGraphLowRiskAutoApply:
    def test_auto_remediated_status(self):
        tf = _make_tf(
            {"exit_code": 2, "stdout": DRIFT_PLAN, "stderr": "", "success": True},
            PARSED_LOW,
            {"exit_code": 0, "stdout": "Apply complete!", "stderr": "", "success": True},
        )
        llm = MagicMock(); llm.complete.return_value = LOW_RISK_LLM
        slack = MagicMock(); slack.send_auto_remediation_notice.return_value = True

        with patch("agent.nodes._get_terraform", return_value=tf), \
             patch("agent.nodes._get_llm", return_value=llm), \
             patch("agent.nodes._get_slack", return_value=slack):
            final = app.invoke(_base_state())

        assert final["final_status"] == "AUTO_REMEDIATED"
        assert final["auto_apply_success"] is True
        slack.send_auto_remediation_notice.assert_called_once()

    def test_apply_failure_escalates(self):
        """If apply fails, the graph escalates."""
        tf = _make_tf(
            {"exit_code": 2, "stdout": DRIFT_PLAN, "stderr": "", "success": True},
            PARSED_LOW,
            {"exit_code": 1, "stdout": "", "stderr": "apply error", "success": False},
        )
        llm = MagicMock(); llm.complete.return_value = LOW_RISK_LLM
        slack = MagicMock(); slack.send_escalation_alert.return_value = True
        aws = MagicMock(); aws.get_recent_changes.return_value = []

        with patch("agent.nodes._get_terraform", return_value=tf), \
             patch("agent.nodes._get_llm", return_value=llm), \
             patch("agent.nodes._get_slack", return_value=slack), \
             patch("agent.nodes._get_aws", return_value=aws):
            final = app.invoke(_base_state())

        assert final["final_status"] == "ESCALATED"


class TestGraphHighRiskEscalate:
    def test_escalated_status(self):
        tf = _make_tf({"exit_code": 2, "stdout": HIGH_RISK_PLAN, "stderr": "", "success": True}, PARSED_HIGH)
        llm = MagicMock(); llm.complete.return_value = HIGH_RISK_LLM
        aws = MagicMock(); aws.get_recent_changes.return_value = [AUDIT_ENTRY]
        slack = MagicMock(); slack.send_escalation_alert.return_value = True

        with patch("agent.nodes._get_terraform", return_value=tf), \
             patch("agent.nodes._get_llm", return_value=llm), \
             patch("agent.nodes._get_aws", return_value=aws), \
             patch("agent.nodes._get_slack", return_value=slack):
            final = app.invoke(_base_state())

        assert final["final_status"] == "ESCALATED"
        assert final["slack_sent"] is True
        slack.send_escalation_alert.assert_called_once()
        tf.run_apply.assert_not_called()

    def test_dangerous_pattern_forces_escalate(self):
        """0.0.0.0/0 in plan output forces ESCALATE even if LLM returns LOW."""
        tf = _make_tf({"exit_code": 2, "stdout": HIGH_RISK_PLAN, "stderr": "", "success": True}, PARSED_HIGH)
        llm = MagicMock(); llm.complete.return_value = LOW_RISK_LLM  # LLM incorrectly says LOW
        aws = MagicMock(); aws.get_recent_changes.return_value = []
        slack = MagicMock(); slack.send_escalation_alert.return_value = True

        with patch("agent.nodes._get_terraform", return_value=tf), \
             patch("agent.nodes._get_llm", return_value=llm), \
             patch("agent.nodes._get_aws", return_value=aws), \
             patch("agent.nodes._get_slack", return_value=slack):
            final = app.invoke(_base_state())

        assert final["final_status"] == "ESCALATED"
        tf.run_apply.assert_not_called()


class TestGraphErrorPath:
    def test_plan_error_status(self):
        tf = _make_tf({"exit_code": 1, "stdout": "", "stderr": "provider not found", "success": False}, {})
        with patch("agent.nodes._get_terraform", return_value=tf):
            final = app.invoke(_base_state())
        assert final["final_status"] == "ERROR"
