"""
LangGraph graph definition for the Self-Healing Terraform Drift Detection Agent.

Compiles the StateGraph with all nodes and conditional edges, then exports
the compiled `app` object for use in entrypoints and tests.
"""

import logging
from typing import Literal

from langgraph.graph import END, START, StateGraph

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
from agent.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conditional edge routing functions
# ---------------------------------------------------------------------------


def _route_after_plan(state: AgentState) -> Literal["parse_drift_node", "finalize_node"]:
    """Route after terraform plan based on exit code.

    Args:
        state: Current agent state.

    Returns:
        Next node name string.
    """
    exit_code: int = state.get("plan_exit_code", 1)
    if exit_code == 2:
        return "parse_drift_node"
    # exit_code 0 (no drift) or 1 (error) — both skip to finalise
    return "finalize_node"


def _route_after_decide(
    state: AgentState,
) -> Literal["auto_apply_node", "fetch_audit_logs_node"]:
    """Route after the decide_action node based on recommended_action.

    Args:
        state: Current agent state.

    Returns:
        Next node name string.
    """
    action: str = state.get("recommended_action", "ESCALATE")
    if action == "AUTO_APPLY":
        return "auto_apply_node"
    return "fetch_audit_logs_node"


def _route_after_apply(
    state: AgentState,
) -> Literal["finalize_node", "fetch_audit_logs_node"]:
    """Route after auto_apply based on success flag.

    On apply failure the node sets recommended_action=ESCALATE; we check that
    to decide whether to escalate or finalize normally.

    Args:
        state: Current agent state.

    Returns:
        Next node name string.
    """
    if state.get("auto_apply_success", False):
        return "finalize_node"
    # Apply failed — escalate via the audit + escalate path
    return "fetch_audit_logs_node"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    """Construct and return the compiled LangGraph StateGraph.

    Returns:
        Compiled graph ready to invoke as `app.invoke(initial_state)`.
    """
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("run_terraform_plan_node", run_terraform_plan_node)
    graph.add_node("parse_drift_node", parse_drift_node)
    graph.add_node("analyze_risk_node", analyze_risk_node)
    graph.add_node("decide_action_node", decide_action_node)
    graph.add_node("auto_apply_node", auto_apply_node)
    graph.add_node("fetch_audit_logs_node", fetch_audit_logs_node)
    graph.add_node("escalate_node", escalate_node)
    graph.add_node("finalize_node", finalize_node)

    # Entry point
    graph.add_edge(START, "run_terraform_plan_node")

    # Conditional: plan → parse or finalise
    graph.add_conditional_edges(
        "run_terraform_plan_node",
        _route_after_plan,
        {
            "parse_drift_node": "parse_drift_node",
            "finalize_node": "finalize_node",
        },
    )

    # Linear path through analysis
    graph.add_edge("parse_drift_node", "analyze_risk_node")
    graph.add_edge("analyze_risk_node", "decide_action_node")

    # Conditional: decide → auto-apply or audit+escalate
    graph.add_conditional_edges(
        "decide_action_node",
        _route_after_decide,
        {
            "auto_apply_node": "auto_apply_node",
            "fetch_audit_logs_node": "fetch_audit_logs_node",
        },
    )

    # Conditional: apply → finalise or escalate
    graph.add_conditional_edges(
        "auto_apply_node",
        _route_after_apply,
        {
            "finalize_node": "finalize_node",
            "fetch_audit_logs_node": "fetch_audit_logs_node",
        },
    )

    # Audit logs always feed into escalation
    graph.add_edge("fetch_audit_logs_node", "escalate_node")
    graph.add_edge("escalate_node", "finalize_node")

    # Terminal
    graph.add_edge("finalize_node", END)

    return graph.compile()


# Singleton compiled graph — import this in entrypoints and tests
app = build_graph()


# ---------------------------------------------------------------------------
# Module entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

    terraform_dir = os.getenv("TERRAFORM_DIR", "terraform")

    initial_state: AgentState = {
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

    logger.info("Starting Self-Healing Terraform Drift Detection Agent.")
    final_state = app.invoke(initial_state)
    logger.info("Agent finished. Final status: %s", final_state.get("final_status"))
    sys.exit(0 if final_state.get("final_status") != "ERROR" else 1)
