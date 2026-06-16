"""
Centralised configuration for the Self-Healing Terraform Infrastructure Drift Detection Agent.

All environment variables and constants are read here and exported as a single Settings instance.
"""

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """Application-wide configuration loaded from environment variables."""

    # Groq API (replacing OpenRouter)
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1/chat/completions"
    
    # Legacy OpenRouter (deprecated, keeping for backward compatibility)
    openrouter_api_keys: List[str] = field(default_factory=list)
    openrouter_model: str = "meta-llama/llama-3.2-1b-instruct:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"

    # Risk thresholds
    risk_auto_apply_threshold: int = 30

    # Terraform
    terraform_timeout_plan: int = 300
    terraform_timeout_apply: int = 600

    # AWS / CloudTrail
    aws_region: str = "us-east-1"
    cloudtrail_lookback_hours: int = 24

    # Slack
    slack_webhook_url: str = ""
    terraform_cloud_workspace_url: str = ""

    # Dangerous patterns to detect regardless of LLM score
    dangerous_patterns: List[str] = field(
        default_factory=lambda: [
            "0.0.0.0/0",
            "::/0",
            '"*"',
            "prod",
            "kms",
            "public_access",
        ]
    )

    def __post_init__(self) -> None:
        """Load values from environment after dataclass initialisation."""
        # Groq API (primary)
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        
        # DEBUG: Print what we got
        import sys
        if self.groq_api_key:
            print(f"[DEBUG] GROQ_API_KEY loaded: {len(self.groq_api_key)} chars, starts with: {self.groq_api_key[:10]}...", file=sys.stderr)
        else:
            print("[DEBUG] GROQ_API_KEY is EMPTY or NOT SET in environment!", file=sys.stderr)
            print(f"[DEBUG] Available env vars: {', '.join([k for k in os.environ.keys() if 'GROQ' in k or 'KEY' in k])}", file=sys.stderr)
        
        self.groq_model = os.getenv("GROQ_MODEL", self.groq_model)
        self.groq_base_url = os.getenv("GROQ_BASE_URL", self.groq_base_url)
        
        # OpenRouter (fallback)
        self.openrouter_api_keys = [
            key.strip()
            for key in [
                os.getenv("OPENROUTER_API_KEY_1", ""),
                os.getenv("OPENROUTER_API_KEY_2", ""),
                os.getenv("OPENROUTER_API_KEY_3", ""),
            ]
            if key and key.strip()
        ]
        self.openrouter_model = os.getenv(
            "OPENROUTER_MODEL", self.openrouter_model
        )
        self.openrouter_base_url = os.getenv(
            "OPENROUTER_BASE_URL", self.openrouter_base_url
        )
        self.risk_auto_apply_threshold = int(
            os.getenv("RISK_AUTO_APPLY_THRESHOLD", str(self.risk_auto_apply_threshold))
        )
        self.terraform_timeout_plan = int(
            os.getenv("TERRAFORM_TIMEOUT_PLAN", str(self.terraform_timeout_plan))
        )
        self.terraform_timeout_apply = int(
            os.getenv("TERRAFORM_TIMEOUT_APPLY", str(self.terraform_timeout_apply))
        )
        self.aws_region = os.getenv("AWS_REGION", self.aws_region)
        self.cloudtrail_lookback_hours = int(
            os.getenv("CLOUDTRAIL_LOOKBACK_HOURS", str(self.cloudtrail_lookback_hours))
        )
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
        self.terraform_cloud_workspace_url = os.getenv(
            "TERRAFORM_CLOUD_WORKSPACE_URL", ""
        )


# Singleton instance used throughout the application
settings = Settings()
