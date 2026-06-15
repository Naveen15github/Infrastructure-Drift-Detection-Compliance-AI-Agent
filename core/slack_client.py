"""
Slack notification client using Block Kit for rich, structured messages.

Provides two notification methods: auto-remediation success and human escalation alert.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List

import requests

from config.settings import settings


class SlackClient:
    """Sends Block Kit messages to a Slack incoming webhook."""

    def __init__(self, webhook_url: str | None = None) -> None:
        """Initialise with a webhook URL.

        Args:
            webhook_url: Optional override. Defaults to settings.slack_webhook_url.
        """
        self._webhook_url: str = webhook_url or settings.slack_webhook_url

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send_auto_remediation_notice(
        self,
        drift_summary: Dict,
        apply_output: str,
    ) -> bool:
        """Send a green success notification after automatic drift remediation.

        Args:
            drift_summary: Parsed drift dict from TerraformClient.parse_plan_output.
            apply_output: Raw stdout from terraform apply.

        Returns:
            True if the webhook returned HTTP 200, False otherwise.
        """
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        changed = (
            drift_summary.get("resources_to_add", [])
            + drift_summary.get("resources_to_change", [])
            + drift_summary.get("resources_to_destroy", [])
        )
        resource_list = "\n".join(f"• `{r}`" for r in changed) or "_(none)_"

        # Trim apply output to avoid hitting Slack's 3000-char block limit
        apply_snippet = (apply_output or "")[:1500]

        blocks = [
            self._header_block("✅ Infrastructure Drift Auto-Remediated"),
            self._divider(),
            self._section_block(f"*Timestamp:* {timestamp}"),
            self._divider(),
            self._section_block(f"*Resources Fixed:*\n{resource_list}"),
            self._divider(),
            self._section_block(
                f"*Terraform Apply Output (truncated):*\n```{apply_snippet}```"
            ),
        ]

        payload = {
            "attachments": [
                {
                    "color": "#36a64f",  # green
                    "blocks": blocks,
                }
            ]
        }
        return self._post(payload)

    def send_escalation_alert(
        self,
        risk_data: Dict,
        drift_summary: Dict,
        audit_logs: List[Dict],
        run_timestamp: str,
    ) -> bool:
        """Send a red escalation alert for high-risk or dangerous drift.

        Args:
            risk_data: LLM risk assessment dict (risk_score, risk_level, reasoning, etc.).
            drift_summary: Parsed drift dict from TerraformClient.parse_plan_output.
            audit_logs: List of CloudTrail audit entries.
            run_timestamp: ISO timestamp string from the agent run.

        Returns:
            True if the webhook returned HTTP 200, False otherwise.
        """
        risk_score = risk_data.get("risk_score", "N/A")
        risk_level = risk_data.get("risk_level", "UNKNOWN")
        reasoning = risk_data.get("reasoning", "No reasoning provided.")
        security_impact = risk_data.get("security_impact", "Unknown impact.")
        recommended_action = risk_data.get("recommended_action", "ESCALATE")
        dangerous_patterns = risk_data.get("dangerous_patterns", [])

        # What changed
        changed = (
            drift_summary.get("resources_to_add", [])
            + drift_summary.get("resources_to_change", [])
            + drift_summary.get("resources_to_destroy", [])
        )
        resource_list = "\n".join(f"• `{r}`" for r in changed) or "_(none)_"

        # Who made the change
        audit_text = self._format_audit_short(audit_logs)

        # Dangerous patterns
        patterns_text = (
            "\n".join(f"⚠️ `{p}`" for p in dangerous_patterns)
            if dangerous_patterns
            else "_None detected by pattern scan_"
        )

        blocks: List[Dict] = [
            self._header_block("🚨 Critical Infrastructure Drift Detected"),
            self._divider(),
            self._section_block(
                f"*Run Timestamp:* {run_timestamp}\n"
                f"*Risk Score:* `{risk_score}/100`  |  *Risk Level:* `{risk_level}`"
            ),
            self._divider(),
            self._section_block(f"*What Changed:*\n{resource_list}"),
            self._divider(),
            self._section_block(f"*Risk Assessment:*\n{reasoning}"),
            self._divider(),
            self._section_block(f"*Dangerous Patterns Found:*\n{patterns_text}"),
            self._divider(),
            self._section_block(f"*Who Made the Change (CloudTrail):*\n{audit_text}"),
            self._divider(),
            self._section_block(f"*Security Impact:*\n{security_impact}"),
            self._divider(),
            self._section_block(
                f"*Recommended Action:*\n`{recommended_action}` — "
                "A human must review and act on this drift."
            ),
        ]

        # Add a "View Details" button if a Terraform Cloud workspace URL is configured
        if settings.terraform_cloud_workspace_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View Details"},
                            "url": settings.terraform_cloud_workspace_url,
                            "style": "danger",
                        }
                    ],
                }
            )

        payload = {
            "attachments": [
                {
                    "color": "#cc0000",  # red
                    "blocks": blocks,
                }
            ]
        }
        return self._post(payload)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _post(self, payload: Dict) -> bool:
        """POST the Block Kit payload to the webhook URL.

        Args:
            payload: Slack message payload dict.

        Returns:
            True on HTTP 200, False otherwise.
        """
        if not self._webhook_url:
            return False
        try:
            response = requests.post(
                self._webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    @staticmethod
    def _header_block(text: str) -> Dict:
        """Return a Slack header block.

        Args:
            text: Header text (plain_text only; no markdown).

        Returns:
            Block Kit header dict.
        """
        return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}

    @staticmethod
    def _divider() -> Dict:
        """Return a Slack divider block."""
        return {"type": "divider"}

    @staticmethod
    def _section_block(text: str) -> Dict:
        """Return a Slack section block with mrkdwn text.

        Args:
            text: Markdown-formatted text content.

        Returns:
            Block Kit section dict.
        """
        return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

    @staticmethod
    def _format_audit_short(audit_logs: List[Dict]) -> str:
        """Format audit log entries into a short Slack-friendly string.

        Args:
            audit_logs: List of dicts from AWSClient.get_recent_changes.

        Returns:
            Formatted string or a placeholder if no entries.
        """
        if not audit_logs:
            return "_No CloudTrail events found in the last 24 hours for these resources._"

        lines = []
        for entry in audit_logs[:5]:  # Cap at 5 to avoid block size limit
            event_time = entry.get("event_time", "unknown time")
            username = entry.get("username", "unknown user")
            event_name = entry.get("event_name", "unknown action")
            resource = entry.get("resource_name", "unknown resource")
            source_ip = entry.get("source_ip", "unknown IP")
            lines.append(
                f"• `{username}` performed `{event_name}` on `{resource}` "
                f"at {event_time} from {source_ip}"
            )
        return "\n".join(lines)
