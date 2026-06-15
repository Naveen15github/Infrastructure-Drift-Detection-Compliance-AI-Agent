"""
State schema for the Self-Healing Terraform Infrastructure Drift Detection Agent.

Defines the TypedDict used as the shared state across all LangGraph nodes.
"""

from typing import TypedDict


class AgentState(TypedDict):
    """Shared state passed between all LangGraph nodes."""

    terraform_dir: str
    plan_exit_code: int
    plan_output: str
    plan_error: str
    parsed_drift: dict
    has_drift: bool
    risk_score: int
    risk_level: str
    risk_reasoning: str
    recommended_action: str
    affected_resources: list
    dangerous_patterns_found: list
    auto_apply_success: bool
    auto_apply_output: str
    audit_log_entries: list
    slack_sent: bool
    final_status: str
    error_message: str
    run_timestamp: str
