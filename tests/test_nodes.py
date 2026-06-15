"""
Tests for agent/nodes.py.

Each node is tested in isolation with all external clients mocked via
the lazy getter functions (e.g. patch("agent.nodes._get_terraform")).
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.nodes import (
    analyze_risk_node,
    auto_apply_node,
    decide_action_node,
    escalate_node,
    fetch_audit_logs_node,
    finalize_node,
    parse_drift_node,
    run_terraform_plan_node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state() -> dict:
    return {
        "terraform_dir": "terraform",
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


def _mock_tf(**methods):
    """Return a MagicMock configured as a TerraformClient stub."""
    m = MagicMock()
    for name, val in methods.items():
        getattr(m, name).return_value = val
    return m


def _mock_llm(response=None, raises=None):
    m = MagicMock()
    if raises:
        m.complete.side_effect = raises
    else:
        m.complete.return_value = response
    return m


def _mock_slack(**methods):
    m = MagicMock()
    for name, val in methods.items():
        getattr(m, name).return_value = val
    return m


def _mock_aws(**methods):
    m = MagicMock()
    for name, val in methods.items():
        getattr(m, name).return_value = val
    return m


# ---------------------------------------------------------------------------
# run_terraform_plan_node
# ---------------------------------------------------------------------------

class TestRunTerraformPlanNode:
    def test_no_drift_sets_final_status(self):
        """Exit code 0 sets has_drift=False and final_status=NO_DRIFT."""
        tf = _mock_tf(run_plan={"exit_code": 0, "stdout": "No changes.", "stderr": "", "success": True})
        with patch("agent.nodes._get_terraform", return_value=tf):
            update = run_terraform_plan_node(_base_state())
        assert update["plan_exit_code"] == 0
        assert update["has_drift"] is False
        assert update["final_status"] == "NO_DRIFT"

    def test_drift_detected(self):
        """Exit code 2 sets has_drift=True."""
        tf = _mock_tf(run_plan={"exit_code": 2, "stdout": "~ change", "stderr": "", "success": True})
        with patch("agent.nodes._get_terraform", return_value=tf):
            update = run_terraform_plan_node(_base_state())
        assert update["plan_exit_code"] == 2
        assert update["has_drift"] is True
        assert update.get("final_status", "") == ""

    def test_error_exit_code(self):
        """Exit code 1 sets final_status=ERROR and records error_message."""
        tf = _mock_tf(run_plan={"exit_code": 1, "stdout": "", "stderr": "init failed", "success": False})
        with patch("agent.nodes._get_terraform", return_value=tf):
            update = run_terraform_plan_node(_base_state())
        assert update["final_status"] == "ERROR"
        assert "init failed" in update["error_message"]


# ---------------------------------------------------------------------------
# parse_drift_node
# ---------------------------------------------------------------------------

class TestParseDriftNode:
    def test_delegates_to_terraform_client(self):
        """Calls parse_plan_output and stores result as parsed_drift."""
        expected = {"resources_to_add": ["aws_s3_bucket.x"], "resources_to_change": [], "resources_to_destroy": [], "raw_changes": ""}
        tf = _mock_tf(parse_plan_output=expected)
        state = _base_state()
        state["plan_output"] = "plan output text"
        with patch("agent.nodes._get_terraform", return_value=tf):
            update = parse_drift_node(state)
        assert update["parsed_drift"] == expected


# ---------------------------------------------------------------------------
# analyze_risk_node
# ---------------------------------------------------------------------------

VALID_RISK_JSON = """{
    "risk_score": 20,
    "risk_level": "LOW",
    "reasoning": "Only tag changes.",
    "affected_resources": ["aws_instance.app"],
    "dangerous_patterns": [],
    "recommended_action": "AUTO_APPLY",
    "security_impact": ""
}"""


class TestAnalyzeRiskNode:
    def test_parses_llm_response(self):
        """Valid LLM JSON is parsed into separate state fields."""
        state = _base_state()
        state["parsed_drift"] = {"resources_to_add": [], "resources_to_change": ["aws_instance.app"], "resources_to_destroy": [], "raw_changes": ""}
        llm = _mock_llm(response=VALID_RISK_JSON)
        with patch("agent.nodes._get_llm", return_value=llm):
            update = analyze_risk_node(state)
        assert update["risk_score"] == 20
        assert update["risk_level"] == "LOW"
        assert update["recommended_action"] == "AUTO_APPLY"

    def test_defaults_to_escalate_on_llm_failure(self):
        """RuntimeError from LLM defaults to CRITICAL/ESCALATE."""
        state = _base_state()
        state["parsed_drift"] = {}
        llm = _mock_llm(raises=RuntimeError("all keys failed"))
        with patch("agent.nodes._get_llm", return_value=llm):
            update = analyze_risk_node(state)
        assert update["risk_level"] == "CRITICAL"
        assert update["recommended_action"] == "ESCALATE"


# ---------------------------------------------------------------------------
# decide_action_node
# ---------------------------------------------------------------------------

class TestDecideActionNode:
    def test_low_risk_auto_apply(self):
        state = _base_state()
        state.update({"risk_score": 20, "risk_level": "LOW", "recommended_action": "AUTO_APPLY", "plan_output": ""})
        assert decide_action_node(state)["recommended_action"] == "AUTO_APPLY"

    def test_high_risk_score_escalates(self):
        state = _base_state()
        state.update({"risk_score": 80, "risk_level": "HIGH", "recommended_action": "AUTO_APPLY", "plan_output": ""})
        assert decide_action_node(state)["recommended_action"] == "ESCALATE"

    def test_dangerous_pattern_forces_escalate(self):
        state = _base_state()
        state.update({
            "risk_score": 10, "risk_level": "LOW", "recommended_action": "AUTO_APPLY",
            "plan_output": 'cidr_blocks = ["0.0.0.0/0"]', "dangerous_patterns_found": [],
        })
        update = decide_action_node(state)
        assert update["recommended_action"] == "ESCALATE"
        assert "0.0.0.0/0" in update["dangerous_patterns_found"]

    def test_medium_risk_escalates(self):
        state = _base_state()
        state.update({"risk_score": 45, "risk_level": "MEDIUM", "recommended_action": "ESCALATE", "plan_output": ""})
        assert decide_action_node(state)["recommended_action"] == "ESCALATE"


# ---------------------------------------------------------------------------
# auto_apply_node
# ---------------------------------------------------------------------------

class TestAutoApplyNode:
    def test_success_sends_slack_notice(self):
        """Successful apply sends Slack notice and sets auto_apply_success=True."""
        tf = _mock_tf(run_apply={"exit_code": 0, "stdout": "Apply complete!", "stderr": "", "success": True})
        slack = _mock_slack(send_auto_remediation_notice=True)
        with patch("agent.nodes._get_terraform", return_value=tf), \
             patch("agent.nodes._get_slack", return_value=slack):
            update = auto_apply_node(_base_state())
        assert update["auto_apply_success"] is True
        slack.send_auto_remediation_notice.assert_called_once()

    def test_failure_escalates(self):
        """Failed apply sets auto_apply_success=False and recommended_action=ESCALATE."""
        tf = _mock_tf(run_apply={"exit_code": 1, "stdout": "", "stderr": "apply error", "success": False})
        with patch("agent.nodes._get_terraform", return_value=tf):
            update = auto_apply_node(_base_state())
        assert update["auto_apply_success"] is False
        assert update["recommended_action"] == "ESCALATE"


# ---------------------------------------------------------------------------
# fetch_audit_logs_node
# ---------------------------------------------------------------------------

class TestFetchAuditLogsNode:
    def test_calls_aws_client_with_all_resources(self):
        """Passes combined affected + parsed resources to AWSClient."""
        state = _base_state()
        state["affected_resources"] = ["aws_instance.app"]
        state["parsed_drift"] = {"resources_to_add": ["aws_s3_bucket.logs"], "resources_to_change": [], "resources_to_destroy": []}
        entry = {"event_time": "t", "username": "u", "event_name": "e", "resource_name": "r", "source_ip": "ip"}
        aws = _mock_aws(get_recent_changes=[entry])
        with patch("agent.nodes._get_aws", return_value=aws):
            update = fetch_audit_logs_node(state)
        called_resources = aws.get_recent_changes.call_args[0][0]
        assert "aws_instance.app" in called_resources
        assert "aws_s3_bucket.logs" in called_resources
        assert len(update["audit_log_entries"]) == 1

    def test_empty_resources_skips_aws_call(self):
        """No resource names → no AWS call, returns empty audit_log_entries."""
        state = _base_state()
        state["affected_resources"] = []
        state["parsed_drift"] = {}
        aws = MagicMock()
        with patch("agent.nodes._get_aws", return_value=aws):
            update = fetch_audit_logs_node(state)
        aws.get_recent_changes.assert_not_called()
        assert update["audit_log_entries"] == []


# ---------------------------------------------------------------------------
# escalate_node
# ---------------------------------------------------------------------------

class TestEscalateNode:
    def test_sends_escalation_and_sets_slack_sent(self):
        """Calls send_escalation_alert and propagates the return value."""
        state = _base_state()
        state.update({
            "risk_score": 90, "risk_level": "CRITICAL", "risk_reasoning": "Very dangerous.",
            "recommended_action": "ESCALATE", "dangerous_patterns_found": ["0.0.0.0/0"],
            "parsed_drift": {}, "audit_log_entries": [], "run_timestamp": "2024-06-01T12:00:00Z",
        })
        slack = _mock_slack(send_escalation_alert=True)
        with patch("agent.nodes._get_slack", return_value=slack):
            update = escalate_node(state)
        assert update["slack_sent"] is True
        slack.send_escalation_alert.assert_called_once()


# ---------------------------------------------------------------------------
# finalize_node
# ---------------------------------------------------------------------------

class TestFinalizeNode:
    def test_no_drift(self):
        state = _base_state(); state["final_status"] = "NO_DRIFT"
        assert finalize_node(state)["final_status"] == "NO_DRIFT"

    def test_auto_remediated(self):
        state = _base_state(); state["auto_apply_success"] = True
        assert finalize_node(state)["final_status"] == "AUTO_REMEDIATED"

    def test_escalated(self):
        state = _base_state(); state["recommended_action"] = "ESCALATE"
        assert finalize_node(state)["final_status"] == "ESCALATED"

    def test_error_preserved(self):
        state = _base_state(); state["final_status"] = "ERROR"
        assert finalize_node(state)["final_status"] == "ERROR"
