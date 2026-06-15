"""
LangGraph node functions for the Self-Healing Terraform Drift Detection Agent.

Each function receives and returns an AgentState dict slice, following
LangGraph's node convention.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict

from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from agent.state import AgentState
from config.settings import settings
from core.aws_client import AWSClient
from core.llm_client import OpenRouterClient
from core.slack_client import SlackClient
from core.terraform_client import TerraformClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared client instances (lazy-initialised to avoid import-time side effects)
# ---------------------------------------------------------------------------

_terraform_client: TerraformClient | None = None
_llm_client: OpenRouterClient | None = None
_slack_client: SlackClient | None = None
_aws_client: AWSClient | None = None


def _get_terraform() -> TerraformClient:
    global _terraform_client
    if _terraform_client is None:
        _terraform_client = TerraformClient()
    return _terraform_client


def _get_llm() -> OpenRouterClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenRouterClient()
    return _llm_client


def _get_slack() -> SlackClient:
    global _slack_client
    if _slack_client is None:
        _slack_client = SlackClient()
    return _slack_client


def _get_aws() -> AWSClient:
    global _aws_client
    if _aws_client is None:
        _aws_client = AWSClient()
    return _aws_client


# ---------------------------------------------------------------------------
# Node 1 — Run Terraform plan
# ---------------------------------------------------------------------------


def run_terraform_plan_node(state: AgentState) -> Dict:
    """Execute terraform init + plan and capture the exit code and output.

    exit_code semantics:
      0 = no changes (no drift)
      1 = error
      2 = changes detected (drift present)

    Args:
        state: Current agent state.

    Returns:
        Partial state update with plan_exit_code, plan_output, plan_error,
        has_drift, run_timestamp, and optionally final_status/error_message.
    """
    run_timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    terraform_dir = state.get("terraform_dir", "terraform")

    logger.info("Running terraform plan in %s", terraform_dir)
    result = _get_terraform().run_plan(terraform_dir)

    exit_code: int = result["exit_code"]
    has_drift: bool = exit_code == 2

    # CRITICAL DEBUG: Always log the exit code
    logger.info("===== TERRAFORM PLAN EXIT CODE: %d =====", exit_code)
    logger.info("===== STDOUT LENGTH: %d chars =====", len(result["stdout"]))
    logger.info("===== STDERR LENGTH: %d chars =====", len(result["stderr"]))
    
    # Log first 500 chars of stdout to see what terraform is saying
    if result["stdout"]:
        logger.info("===== TERRAFORM STDOUT (first 500 chars) =====")
        logger.info(result["stdout"][:500])
        logger.info("===== TERRAFORM STDOUT (FULL OUTPUT) =====")
        logger.info(result["stdout"])
    
    # Log stderr if present
    if result["stderr"]:
        logger.info("===== TERRAFORM STDERR =====")
        logger.info(result["stderr"][:500])

    update: Dict = {
        "plan_exit_code": exit_code,
        "plan_output": result["stdout"],
        "plan_error": result["stderr"],
        "has_drift": has_drift,
        "run_timestamp": run_timestamp,
    }

    if exit_code == 0:
        logger.info("No drift detected.")
        update["final_status"] = "NO_DRIFT"
    elif exit_code == 1:
        logger.error("Terraform plan error: %s", result["stderr"])
        update["final_status"] = "ERROR"
        update["error_message"] = result["stderr"]
    else:
        logger.info("Drift detected (exit code 2). Proceeding to parse.")

    return update


# ---------------------------------------------------------------------------
# Node 2 — Parse drift from plan output
# ---------------------------------------------------------------------------


def parse_drift_node(state: AgentState) -> Dict:
    """Parse raw terraform plan output into a structured drift dict.

    Args:
        state: Current agent state (requires plan_output).

    Returns:
        Partial state update with parsed_drift.
    """
    raw_output: str = state.get("plan_output", "")
    logger.info("Parsing terraform plan output (%d chars).", len(raw_output))

    parsed = _get_terraform().parse_plan_output(raw_output)
    logger.info(
        "Parsed drift — add: %d, change: %d, destroy: %d",
        len(parsed["resources_to_add"]),
        len(parsed["resources_to_change"]),
        len(parsed["resources_to_destroy"]),
    )

    return {"parsed_drift": parsed}


# ---------------------------------------------------------------------------
# Node 3 — LLM risk analysis
# ---------------------------------------------------------------------------


def analyze_risk_node(state: AgentState) -> Dict:
    """Send parsed drift to the LLM and receive a structured risk assessment.

    Args:
        state: Current agent state (requires parsed_drift).

    Returns:
        Partial state update with risk_score, risk_level, risk_reasoning,
        recommended_action, affected_resources, and dangerous_patterns_found.
    """
    parsed_drift: Dict = state.get("parsed_drift", {})
    user_prompt = build_user_prompt(parsed_drift)

    logger.info("Sending drift to LLM for risk analysis (model: %s).", settings.openrouter_model)

    try:
        raw_response = _get_llm().complete(SYSTEM_PROMPT, user_prompt)
        risk_data = json.loads(raw_response)
    except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
        logger.error("LLM analysis failed: %s. Defaulting to ESCALATE.", exc)
        # Safe default on failure: treat as high risk
        risk_data = {
            "risk_score": 100,
            "risk_level": "CRITICAL",
            "reasoning": f"LLM analysis failed ({exc}). Defaulting to escalation.",
            "affected_resources": [],
            "dangerous_patterns": [],
            "recommended_action": "ESCALATE",
            "security_impact": "Unknown — LLM call failed.",
        }

    return {
        "risk_score": int(risk_data.get("risk_score", 100)),
        "risk_level": str(risk_data.get("risk_level", "CRITICAL")),
        "risk_reasoning": str(risk_data.get("reasoning", "")),
        "recommended_action": str(risk_data.get("recommended_action", "ESCALATE")),
        "affected_resources": list(risk_data.get("affected_resources", [])),
        "dangerous_patterns_found": list(risk_data.get("dangerous_patterns", [])),
    }


# ---------------------------------------------------------------------------
# Node 4 — Decide action (router — no side effects)
# ---------------------------------------------------------------------------


def decide_action_node(state: AgentState) -> Dict:
    """Determine whether to auto-apply or escalate based on risk score and patterns.

    Overrides LLM recommendation to ESCALATE if any dangerous pattern is found in
    the raw plan output, regardless of the LLM's risk_score.

    Args:
        state: Current agent state (requires risk_score, risk_level,
               dangerous_patterns_found, plan_output).

    Returns:
        Partial state update with recommended_action (may override LLM decision).
    """
    risk_score: int = state.get("risk_score", 100)
    risk_level: str = state.get("risk_level", "CRITICAL")
    llm_action: str = state.get("recommended_action", "ESCALATE")
    plan_output: str = state.get("plan_output", "")
    dangerous_patterns_found: list = state.get("dangerous_patterns_found", [])

    # Pattern-scan the raw plan output for known dangerous strings
    pattern_triggered: bool = any(
        pattern.lower() in plan_output.lower()
        for pattern in settings.dangerous_patterns
    )

    if pattern_triggered:
        matched = [
            p for p in settings.dangerous_patterns
            if p.lower() in plan_output.lower()
        ]
        logger.warning("Dangerous patterns found in plan output: %s. Forcing ESCALATE.", matched)
        dangerous_patterns_found = list(set(dangerous_patterns_found + matched))
        return {
            "recommended_action": "ESCALATE",
            "dangerous_patterns_found": dangerous_patterns_found,
        }

    # Trust LLM for non-dangerous patterns; validate threshold as a safety belt
    if risk_score <= settings.risk_auto_apply_threshold and risk_level == "LOW":
        action = "AUTO_APPLY"
    else:
        action = "ESCALATE"

    if action != llm_action:
        logger.info(
            "Overriding LLM action %s → %s based on risk_score=%d / risk_level=%s.",
            llm_action, action, risk_score, risk_level,
        )

    return {"recommended_action": action}


# ---------------------------------------------------------------------------
# Node 5 — Auto-apply
# ---------------------------------------------------------------------------


def auto_apply_node(state: AgentState) -> Dict:
    """Run terraform apply -auto-approve and notify Slack on success or failure.

    Args:
        state: Current agent state (requires terraform_dir, parsed_drift).

    Returns:
        Partial state update with auto_apply_success, auto_apply_output,
        slack_sent, and (on failure) recommended_action set to ESCALATE.
    """
    terraform_dir: str = state.get("terraform_dir", "terraform")
    parsed_drift: Dict = state.get("parsed_drift", {})

    logger.info("Running terraform apply in %s.", terraform_dir)
    result = _get_terraform().run_apply(terraform_dir)

    success: bool = result["success"]
    apply_output: str = result["stdout"] + result["stderr"]

    if success:
        logger.info("Terraform apply succeeded. Sending Slack auto-remediation notice.")
        sent = _get_slack().send_auto_remediation_notice(parsed_drift, apply_output)
        return {
            "auto_apply_success": True,
            "auto_apply_output": apply_output,
            "slack_sent": sent,
        }
    else:
        logger.error("Terraform apply FAILED. Escalating to human.")
        return {
            "auto_apply_success": False,
            "auto_apply_output": apply_output,
            "recommended_action": "ESCALATE",
            "error_message": apply_output,
        }


# ---------------------------------------------------------------------------
# Node 6 — Fetch CloudTrail audit logs
# ---------------------------------------------------------------------------


def fetch_audit_logs_node(state: AgentState) -> Dict:
    """Query AWS CloudTrail for events matching the drifted resources.

    Args:
        state: Current agent state (requires affected_resources).

    Returns:
        Partial state update with audit_log_entries.
    """
    affected: list = state.get("affected_resources", [])
    parsed_drift: Dict = state.get("parsed_drift", {})

    # Combine LLM-identified resources with parse-extracted resources for wider coverage
    all_resources = list(
        set(affected)
        | set(parsed_drift.get("resources_to_add", []))
        | set(parsed_drift.get("resources_to_change", []))
        | set(parsed_drift.get("resources_to_destroy", []))
    )

    if not all_resources:
        logger.info("No resource names to look up in CloudTrail.")
        return {"audit_log_entries": []}

    logger.info("Fetching CloudTrail events for %d resource(s).", len(all_resources))
    entries = _get_aws().get_recent_changes(all_resources)
    logger.info("Found %d CloudTrail event(s).", len(entries))

    return {"audit_log_entries": entries}


# ---------------------------------------------------------------------------
# Node 7 — Escalate to human via Slack
# ---------------------------------------------------------------------------


def escalate_node(state: AgentState) -> Dict:
    """Send a rich Slack escalation alert for high-risk or dangerous drift.

    Args:
        state: Current agent state.

    Returns:
        Partial state update with slack_sent.
    """
    risk_data = {
        "risk_score": state.get("risk_score", 100),
        "risk_level": state.get("risk_level", "UNKNOWN"),
        "reasoning": state.get("risk_reasoning", ""),
        "recommended_action": state.get("recommended_action", "ESCALATE"),
        "dangerous_patterns": state.get("dangerous_patterns_found", []),
        "security_impact": "Manual review required.",
    }

    logger.info(
        "Sending escalation alert. Risk score=%d, level=%s.",
        risk_data["risk_score"],
        risk_data["risk_level"],
    )

    sent = _get_slack().send_escalation_alert(
        risk_data=risk_data,
        drift_summary=state.get("parsed_drift", {}),
        audit_logs=state.get("audit_log_entries", []),
        run_timestamp=state.get("run_timestamp", "N/A"),
    )

    return {"slack_sent": sent}


# ---------------------------------------------------------------------------
# Node 8 — Finalise run
# ---------------------------------------------------------------------------


def finalize_node(state: AgentState) -> Dict:
    """Log and record the final run status.

    Args:
        state: Current agent state.

    Returns:
        Partial state update with final_status.
    """
    existing_status: str = state.get("final_status", "")
    auto_apply_success: bool = state.get("auto_apply_success", False)
    recommended_action: str = state.get("recommended_action", "")
    error_message: str = state.get("error_message", "")

    if existing_status in ("NO_DRIFT", "ERROR"):
        final_status = existing_status
    elif recommended_action == "ESCALATE":
        final_status = "ESCALATED"
    elif auto_apply_success:
        final_status = "AUTO_REMEDIATED"
    elif error_message:
        final_status = "ERROR"
    else:
        final_status = "NO_DRIFT"

    logger.info(
        "Run complete. Status=%s | Timestamp=%s",
        final_status,
        state.get("run_timestamp", "N/A"),
    )

    return {"final_status": final_status}
