"""
Tests for core/aws_client.py.

Covers get_recent_changes pagination, event normalisation, deduplication,
CloudTrail error handling, and format_audit_log output.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.aws_client import AWSClient


def _make_cloudtrail_event(
    username: str = "alice",
    event_name: str = "AuthorizeSecurityGroupIngress",
    resource_name: str = "app-sg",
    source_ip: str = "1.2.3.4",
) -> dict:
    """Build a minimal mock CloudTrail event dict."""
    return {
        "Username": username,
        "EventTime": datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "EventName": event_name,
        "SourceIPAddress": source_ip,
        "Resources": [{"ResourceName": resource_name}],
    }


class TestGetRecentChanges:
    """Tests for AWSClient.get_recent_changes."""

    def _make_paginator(self, events: list) -> MagicMock:
        """Create a mock paginator that yields one page of events."""
        page = {"Events": events}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = iter([page])
        return mock_paginator

    def test_returns_normalised_entries(self):
        """Returned entries contain the expected normalised keys."""
        event = _make_cloudtrail_event()
        client = AWSClient(region="us-east-1")

        with patch.object(client, "_client") as mock_ct:
            mock_ct.get_paginator.return_value = self._make_paginator([event])
            results = client.get_recent_changes(["aws_security_group.app"])

        assert len(results) == 1
        entry = results[0]
        assert entry["username"] == "alice"
        assert entry["event_name"] == "AuthorizeSecurityGroupIngress"
        assert entry["source_ip"] == "1.2.3.4"

    def test_deduplicates_identical_events(self):
        """Duplicate events for the same resource appear only once."""
        event = _make_cloudtrail_event()
        client = AWSClient(region="us-east-1")

        with patch.object(client, "_client") as mock_ct:
            # Return the same event from two resource lookups
            mock_ct.get_paginator.return_value = self._make_paginator([event, event])
            results = client.get_recent_changes(["aws_security_group.app"])

        assert len(results) == 1

    def test_empty_resource_list_returns_empty(self):
        """An empty resource_names list returns an empty result without API calls."""
        client = AWSClient(region="us-east-1")
        with patch.object(client, "_client") as mock_ct:
            results = client.get_recent_changes([])

        mock_ct.get_paginator.assert_not_called()
        assert results == []

    def test_cloudtrail_error_returns_error_entry(self):
        """A botocore ClientError is caught and returned as an error entry."""
        from botocore.exceptions import ClientError

        client = AWSClient(region="us-east-1")

        error_response = {"Error": {"Code": "AccessDenied", "Message": "denied"}}
        with patch.object(client, "_client") as mock_ct:
            mock_ct.get_paginator.return_value = MagicMock(
                paginate=MagicMock(
                    side_effect=ClientError(error_response, "LookupEvents")
                )
            )
            results = client.get_recent_changes(["aws_instance.app"])

        assert len(results) == 1
        assert results[0]["username"] == "lookup-failed"
        assert "error" in results[0]

    def test_event_time_formatted_as_string(self):
        """event_time is returned as a formatted string, not a datetime object."""
        event = _make_cloudtrail_event()
        client = AWSClient(region="us-east-1")

        with patch.object(client, "_client") as mock_ct:
            mock_ct.get_paginator.return_value = self._make_paginator([event])
            results = client.get_recent_changes(["aws_security_group.app"])

        assert isinstance(results[0]["event_time"], str)
        assert "2024" in results[0]["event_time"]


class TestFormatAuditLog:
    """Tests for AWSClient.format_audit_log."""

    def test_empty_list_returns_no_events_string(self):
        """Empty entries list returns the 'No CloudTrail events found' message."""
        result = AWSClient.format_audit_log([])
        assert "No CloudTrail events found" in result

    def test_formats_single_entry(self):
        """Single entry is formatted with all expected fields."""
        entries = [
            {
                "event_time": "2024-06-01 12:00:00 UTC",
                "username": "bob",
                "event_name": "DeleteBucket",
                "resource_name": "aws_s3_bucket.logs",
                "source_ip": "10.0.0.1",
            }
        ]
        result = AWSClient.format_audit_log(entries)
        assert "bob" in result
        assert "DeleteBucket" in result
        assert "aws_s3_bucket.logs" in result
        assert "10.0.0.1" in result

    def test_formats_multiple_entries(self):
        """Multiple entries each appear on their own line."""
        entries = [
            {
                "event_time": "t1",
                "username": "alice",
                "event_name": "AuthorizeIngress",
                "resource_name": "sg-001",
                "source_ip": "1.1.1.1",
            },
            {
                "event_time": "t2",
                "username": "bob",
                "event_name": "DeleteBucket",
                "resource_name": "bucket-001",
                "source_ip": "2.2.2.2",
            },
        ]
        result = AWSClient.format_audit_log(entries)
        lines = [l for l in result.split("\n") if l.strip()]
        # Header line + 2 entry lines
        assert len(lines) >= 3
