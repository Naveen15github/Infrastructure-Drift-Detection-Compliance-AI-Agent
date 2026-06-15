"""
Tests for core/terraform_client.py.

Covers run_plan exit codes 0, 1, and 2, run_apply success/failure,
and parse_plan_output extraction logic.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.terraform_client import TerraformClient


SAMPLE_PLAN_NO_DRIFT = """
No changes. Your infrastructure matches the configuration.
"""

SAMPLE_PLAN_DRIFT = """
Terraform will perform the following actions:

  # aws_instance.app will be updated in-place
  ~ resource "aws_instance" "app" {
      ~ tags = {
          ~ "Name" = "old-name" -> "new-name"
        }
    }

  # aws_s3_bucket.logs will be created
  + resource "aws_s3_bucket" "logs" {
      + bucket = "my-logs-bucket"
    }

Plan: 1 to add, 1 to change, 0 to destroy.
"""

SAMPLE_PLAN_DESTROY = """
Terraform will perform the following actions:

  # aws_security_group.app will be destroyed
  - resource "aws_security_group" "app" {
      - name = "app-sg"
    }

Plan: 0 to add, 0 to change, 1 to destroy.
"""


def _mock_run(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a mock subprocess.CompletedProcess."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestRunPlan:
    """Tests for TerraformClient.run_plan."""

    def _patch_run(self, side_effects):
        """Helper to patch subprocess.run with a list of return values."""
        return patch(
            "core.terraform_client.subprocess.run",
            side_effect=side_effects,
        )

    def test_exit_code_0_no_drift(self):
        """Exit code 0 from plan → success=True, exit_code=0."""
        init_ok = _mock_run(0)
        plan_ok = _mock_run(0, stdout=SAMPLE_PLAN_NO_DRIFT)

        with self._patch_run([init_ok, plan_ok]):
            result = TerraformClient().run_plan("terraform")

        assert result["exit_code"] == 0
        assert result["success"] is True
        assert SAMPLE_PLAN_NO_DRIFT in result["stdout"]

    def test_exit_code_2_drift_detected(self):
        """Exit code 2 from plan → success=True (drift is not an error), exit_code=2."""
        init_ok = _mock_run(0)
        plan_drift = _mock_run(2, stdout=SAMPLE_PLAN_DRIFT)

        with self._patch_run([init_ok, plan_drift]):
            result = TerraformClient().run_plan("terraform")

        assert result["exit_code"] == 2
        assert result["success"] is True

    def test_exit_code_1_error(self):
        """Exit code 1 from plan → success=False."""
        init_ok = _mock_run(0)
        plan_err = _mock_run(1, stderr="Error: provider not found")

        with self._patch_run([init_ok, plan_err]):
            result = TerraformClient().run_plan("terraform")

        assert result["exit_code"] == 1
        assert result["success"] is False

    def test_init_failure_returns_error(self):
        """If terraform init fails, skip plan and return exit_code=1."""
        init_fail = _mock_run(1, stderr="init error")

        with self._patch_run([init_fail]):
            result = TerraformClient().run_plan("terraform")

        assert result["exit_code"] == 1
        assert result["success"] is False
        assert "init failed" in result["stderr"]

    def test_terraform_not_found(self):
        """FileNotFoundError → returns error dict with helpful message."""
        with patch(
            "core.terraform_client.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = TerraformClient().run_plan("terraform")

        assert result["exit_code"] == 1
        assert "not found" in result["stderr"].lower()


class TestRunApply:
    """Tests for TerraformClient.run_apply."""

    def test_apply_success(self):
        """apply exit code 0 → success=True."""
        apply_ok = _mock_run(0, stdout="Apply complete!")

        with patch("core.terraform_client.subprocess.run", return_value=apply_ok):
            result = TerraformClient().run_apply("terraform")

        assert result["success"] is True
        assert "Apply complete" in result["stdout"]

    def test_apply_failure(self):
        """apply exit code 1 → success=False."""
        apply_fail = _mock_run(1, stderr="Error: timeout")

        with patch("core.terraform_client.subprocess.run", return_value=apply_fail):
            result = TerraformClient().run_apply("terraform")

        assert result["success"] is False
        assert result["exit_code"] == 1


class TestParsePlanOutput:
    """Tests for TerraformClient.parse_plan_output."""

    def test_parses_resources_to_add(self):
        """Extracts resources flagged as 'will be created'."""
        client = TerraformClient()
        result = client.parse_plan_output(SAMPLE_PLAN_DRIFT)
        assert "aws_s3_bucket.logs" in result["resources_to_add"]

    def test_parses_resources_to_change(self):
        """Extracts resources flagged as 'will be updated in-place'."""
        client = TerraformClient()
        result = client.parse_plan_output(SAMPLE_PLAN_DRIFT)
        assert "aws_instance.app" in result["resources_to_change"]

    def test_parses_resources_to_destroy(self):
        """Extracts resources flagged as 'will be destroyed'."""
        client = TerraformClient()
        result = client.parse_plan_output(SAMPLE_PLAN_DESTROY)
        assert "aws_security_group.app" in result["resources_to_destroy"]

    def test_empty_output_returns_empty_lists(self):
        """Empty plan output returns empty lists without raising."""
        client = TerraformClient()
        result = client.parse_plan_output("")
        assert result["resources_to_add"] == []
        assert result["resources_to_change"] == []
        assert result["resources_to_destroy"] == []

    def test_raw_changes_extracted(self):
        """raw_changes captures the change detail block."""
        client = TerraformClient()
        result = client.parse_plan_output(SAMPLE_PLAN_DRIFT)
        assert "aws_instance" in result["raw_changes"]
