"""
AWS CloudTrail client for fetching recent infrastructure change events.

Used to identify who made a manual change that caused Terraform drift.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config.settings import settings


class AWSClient:
    """Fetches CloudTrail events to identify the actor behind infrastructure drift."""

    def __init__(self, region: str | None = None) -> None:
        """Initialise the boto3 CloudTrail client.

        Args:
            region: AWS region string. Defaults to settings.aws_region.
        """
        self._region: str = region or settings.aws_region
        self._client = boto3.client("cloudtrail", region_name=self._region)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_recent_changes(
        self,
        resource_names: List[str],
        hours: int | None = None,
    ) -> List[Dict]:
        """Look up CloudTrail events for the given resource names.

        Args:
            resource_names: List of Terraform resource addresses or AWS resource names
                            to search for in CloudTrail.
            hours: How many hours back to search. Defaults to settings.cloudtrail_lookback_hours.

        Returns:
            List of dicts, each with keys:
              event_time (str), username (str), event_name (str),
              resource_name (str), source_ip (str).
        """
        lookback = hours or settings.cloudtrail_lookback_hours
        start_time = datetime.now(tz=timezone.utc) - timedelta(hours=lookback)
        results: List[Dict] = []

        for resource_name in resource_names:
            # Strip Terraform address prefixes (e.g. "aws_instance.web" → "web")
            short_name = resource_name.split(".")[-1].strip("[]\"'")

            try:
                paginator = self._client.get_paginator("lookup_events")
                pages = paginator.paginate(
                    StartTime=start_time,
                    EndTime=datetime.now(tz=timezone.utc),
                    LookupAttributes=[
                        {"AttributeKey": "ResourceName", "AttributeValue": short_name}
                    ],
                )
                for page in pages:
                    for event in page.get("Events", []):
                        results.append(self._normalise_event(event, resource_name))

            except (BotoCoreError, ClientError) as exc:
                # Non-fatal: log and continue with other resources
                results.append(
                    {
                        "event_time": "N/A",
                        "username": "lookup-failed",
                        "event_name": "N/A",
                        "resource_name": resource_name,
                        "source_ip": "N/A",
                        "error": str(exc),
                    }
                )

        # Deduplicate by (event_time, username, event_name, resource_name)
        seen = set()
        unique: List[Dict] = []
        for entry in results:
            key = (
                entry.get("event_time"),
                entry.get("username"),
                entry.get("event_name"),
                entry.get("resource_name"),
            )
            if key not in seen:
                seen.add(key)
                unique.append(entry)

        return unique

    @staticmethod
    def format_audit_log(entries: List[Dict]) -> str:
        """Format audit log entries as a human-readable multi-line string.

        Args:
            entries: List of dicts returned by get_recent_changes.

        Returns:
            Formatted string suitable for inclusion in a Slack message or log.
        """
        if not entries:
            return "No CloudTrail events found."

        lines = ["CloudTrail Audit Log:"]
        for entry in entries:
            lines.append(
                f"  [{entry.get('event_time', 'N/A')}] "
                f"User: {entry.get('username', 'N/A')} | "
                f"Action: {entry.get('event_name', 'N/A')} | "
                f"Resource: {entry.get('resource_name', 'N/A')} | "
                f"Source IP: {entry.get('source_ip', 'N/A')}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_event(event: Dict, resource_name: str) -> Dict:
        """Extract the fields we care about from a raw CloudTrail event dict.

        Args:
            event: Raw event dict from the CloudTrail API.
            resource_name: The Terraform resource name used in the lookup.

        Returns:
            Normalised dict with our standard keys.
        """
        username = (
            event.get("Username")
            or event.get("CloudTrailEvent", {})
        )
        if isinstance(username, dict):
            username = username.get("userIdentity", {}).get("arn", "unknown")

        event_time = event.get("EventTime")
        if isinstance(event_time, datetime):
            event_time = event_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            event_time = str(event_time)

        return {
            "event_time": event_time,
            "username": str(username),
            "event_name": event.get("EventName", "N/A"),
            "resource_name": resource_name,
            "source_ip": event.get("SourceIPAddress", "N/A"),
        }
