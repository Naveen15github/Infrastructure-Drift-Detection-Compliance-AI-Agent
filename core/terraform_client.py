"""
Terraform CLI wrapper for running plan and apply operations.

Handles subprocess execution, output capture, timeout enforcement, and
lightweight parsing of plan output into structured drift data.
"""

import re
import subprocess
from pathlib import Path
from typing import Dict, List

from config.settings import settings


class TerraformClient:
    """Wrapper around the Terraform CLI binary.

    Runs terraform init, plan, and apply as subprocesses and captures
    all output for downstream processing.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_plan(self, terraform_dir: str) -> Dict:
        """Run `terraform init -upgrade` then `terraform plan -out=tfplan -detailed-exitcode`.

        Args:
            terraform_dir: Path to the directory containing .tf files.

        Returns:
            Dict with keys: exit_code (int), stdout (str), stderr (str), success (bool).
            exit_code semantics:
              0 = no changes needed
              1 = error occurred
              2 = changes detected (drift)
        """
        tf_path = str(Path(terraform_dir).resolve())

        # Always init first so providers are available
        init_result = self._run_command(
            ["terraform", "init", "-upgrade"],
            cwd=tf_path,
            timeout=settings.terraform_timeout_plan,
        )
        if init_result["exit_code"] != 0:
            return {
                "exit_code": 1,
                "stdout": init_result["stdout"],
                "stderr": f"terraform init failed:\n{init_result['stderr']}",
                "success": False,
            }

        plan_result = self._run_command(
            ["terraform", "plan", "-out=tfplan", "-detailed-exitcode"],
            cwd=tf_path,
            timeout=settings.terraform_timeout_plan,
        )

        # exit code 2 means changes; not a failure
        success = plan_result["exit_code"] in (0, 2)
        return {
            "exit_code": plan_result["exit_code"],
            "stdout": plan_result["stdout"],
            "stderr": plan_result["stderr"],
            "success": success,
        }

    def run_apply(self, terraform_dir: str) -> Dict:
        """Run `terraform apply -auto-approve tfplan`.

        Args:
            terraform_dir: Path to the directory containing .tf files and tfplan.

        Returns:
            Dict with keys: exit_code (int), stdout (str), stderr (str), success (bool).
        """
        tf_path = str(Path(terraform_dir).resolve())

        result = self._run_command(
            ["terraform", "apply", "-auto-approve", "tfplan"],
            cwd=tf_path,
            timeout=settings.terraform_timeout_apply,
        )
        return {
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "success": result["exit_code"] == 0,
        }

    def parse_plan_output(self, raw_output: str) -> Dict:
        """Extract structured change information from raw terraform plan stdout.

        Args:
            raw_output: Combined stdout from terraform plan.

        Returns:
            Dict with keys:
              resources_to_add (list[str])
              resources_to_change (list[str])
              resources_to_destroy (list[str])
              raw_changes (str) — the change-detail blocks extracted verbatim
        """
        resources_to_add: List[str] = self._extract_resources(raw_output, r"will be created")
        resources_to_change: List[str] = self._extract_resources(raw_output, r"will be updated in-place|must be replaced")
        resources_to_destroy: List[str] = self._extract_resources(raw_output, r"will be destroyed")

        raw_changes = self._extract_change_blocks(raw_output)

        return {
            "resources_to_add": resources_to_add,
            "resources_to_change": resources_to_change,
            "resources_to_destroy": resources_to_destroy,
            "raw_changes": raw_changes,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_command(cmd: List[str], cwd: str, timeout: int) -> Dict:
        """Execute a subprocess command and capture output.

        Args:
            cmd: Command and argument list.
            cwd: Working directory for the subprocess.
            timeout: Maximum seconds before TimeoutExpired is raised.

        Returns:
            Dict with exit_code, stdout, stderr.
        """
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s: {exc}",
            }
        except FileNotFoundError:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": "terraform binary not found. Is it installed and on PATH?",
            }

    @staticmethod
    def _extract_resources(plan_output: str, action_pattern: str) -> List[str]:
        """Find resource addresses that match a given action verb pattern.

        Terraform plan lines look like:
          # aws_instance.web will be created
          # aws_security_group.main must be replaced

        Args:
            plan_output: Raw plan stdout.
            action_pattern: Regex pattern for the action verb phrase.

        Returns:
            Sorted list of unique resource address strings.
        """
        pattern = r"#\s+([\w.\[\]\"']+)\s+(?:" + action_pattern + r")"
        matches = re.findall(pattern, plan_output)
        return sorted(set(matches))

    @staticmethod
    def _extract_change_blocks(plan_output: str) -> str:
        """Extract the attribute-level change blocks from the plan output.

        Captures the section between the first resource block header and
        the "Plan:" summary line.

        Args:
            plan_output: Raw plan stdout.

        Returns:
            The extracted change-detail text, or the full output if markers not found.
        """
        # Find the start of resource change blocks
        start_match = re.search(r"^Terraform will perform the following actions:", plan_output, re.MULTILINE)
        end_match = re.search(r"^Plan:", plan_output, re.MULTILINE)

        if start_match and end_match:
            return plan_output[start_match.start() : end_match.end()].strip()

        # Fallback: return the whole output (it may be a custom mock)
        return plan_output.strip()
