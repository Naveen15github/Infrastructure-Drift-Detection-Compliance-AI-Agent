# Self-Healing Terraform Infrastructure Drift Detection Agent

An autonomous system that detects Terraform infrastructure drift on a schedule, uses an LLM to evaluate risk, automatically applies low-risk fixes, and escalates high-risk drift to Slack with full context — including who made the change (from AWS CloudTrail).

---

## Architecture

```
GitHub Actions (every 6h)
        │
        ▼
┌──────────────────────────────────────────────────────────────────┐
│                    LangGraph Agent                                │
│                                                                  │
│  START                                                           │
│    │                                                             │
│    ▼                                                             │
│  run_terraform_plan_node  ──(exit 0/1)──► finalize_node ──► END │
│    │ (exit code 2: drift)                                        │
│    ▼                                                             │
│  parse_drift_node                                                │
│    │                                                             │
│    ▼                                                             │
│  analyze_risk_node  (OpenRouter LLM)                            │
│    │                                                             │
│    ▼                                                             │
│  decide_action_node                                              │
│    │                        │                                    │
│  (LOW risk ≤30)         (HIGH risk / dangerous pattern)         │
│    │                        │                                    │
│    ▼                        ▼                                    │
│  auto_apply_node      fetch_audit_logs_node (CloudTrail)        │
│    │ (success)              │                                    │
│    │          (failure) ────┤                                    │
│    │                        ▼                                    │
│    │                  escalate_node (Slack 🚨)                  │
│    │                        │                                    │
│    └───────────────────────►▼                                    │
│                        finalize_node ──► END                     │
└──────────────────────────────────────────────────────────────────┘
         │                                │
         ▼                                ▼
   Slack ✅ Auto-remediated        Slack 🚨 Escalation alert
```

---

## 1. What This Project Does

When you manage cloud infrastructure with Terraform, people sometimes make manual changes in the AWS console — opening a port, modifying a tag, changing an IAM policy. These out-of-band changes create **drift**: your Terraform state no longer matches reality.

This agent:

1. **Detects drift** by running `terraform plan` every 6 hours (or on demand)
2. **Evaluates risk** by sending the plan diff to an LLM (via OpenRouter) acting as a senior DevSecOps engineer
3. **Auto-remediates** tag changes, name updates, and other low-impact drift by running `terraform apply` automatically
4. **Escalates** dangerous changes (security groups opened to `0.0.0.0/0`, IAM wildcards, production resource deletions) to Slack with the full context: what changed, who changed it (from CloudTrail), and the assessed security impact

---

## 2. Prerequisites

| Tool | Minimum Version | Installation |
|------|----------------|--------------|
| Python | 3.11+ | https://www.python.org/downloads/ |
| Terraform CLI | 1.5+ | https://developer.hashicorp.com/terraform/install |
| AWS account | — | https://aws.amazon.com/free/ |
| OpenRouter account | — | https://openrouter.ai |
| Slack workspace | — | https://slack.com |
| Git | 2.x | https://git-scm.com |

---

## 3. Step-by-Step Local Setup

### Clone the repository

```bash
git clone https://github.com/your-org/self-healing-terraform.git
cd self-healing-terraform
```

### Create a Python virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows PowerShell
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Set up environment variables

```bash
cp .env.example .env
# Now edit .env with your real values (see sections 6, 7, 8 below)
```

---

## 4. AWS Credentials and Required IAM Permissions

The agent needs an IAM user or role with the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TerraformStateAndCore",
      "Effect": "Allow",
      "Action": [
        "ec2:*",
        "s3:*",
        "iam:*",
        "cloudtrail:LookupEvents",
        "logs:*"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Tip for production**: Scope the `ec2:*`, `s3:*`, and `iam:*` actions to the specific resources managed by your Terraform configuration to follow least-privilege.

### Create an IAM user for local testing

1. Go to **IAM → Users → Create user**
2. Attach the policy above
3. Create an access key under **Security credentials**
4. Copy `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` into `.env`

---

## 5. Initialise and Apply the Sample Terraform Infrastructure

The `terraform/` directory contains a realistic sample AWS setup (VPC, subnet, security group, EC2 instance, S3 bucket, IAM role).

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

terraform init
terraform plan      # Review what will be created
terraform apply     # Type "yes" to confirm
```

After apply completes, note the outputs:

```
vpc_id              = "vpc-0abc123..."
instance_id         = "i-0abc123..."
s3_bucket_name      = "drift-agent-dev-app-123456789012"
security_group_id   = "sg-0abc123..."
```

---

## 6. OpenRouter API Keys

1. Sign up at https://openrouter.ai
2. Go to **Account → API Keys → Create Key**
3. Create three separate keys (to provide rotation headroom)
4. Add them to `.env`:

```
OPENROUTER_API_KEY_1=sk-or-v1-...
OPENROUTER_API_KEY_2=sk-or-v1-...
OPENROUTER_API_KEY_3=sk-or-v1-...
```

The agent uses the free model `nvidia/llama-3.1-nemotron-ultra-253b-v1:free` by default. This is a high-quality model with generous free-tier limits.

---

## 7. Slack Webhook Setup

1. Go to https://api.slack.com/apps → **Create New App → From scratch**
2. Name it (e.g. "Terraform Drift Agent") and choose your workspace
3. Under **Features → Incoming Webhooks**, toggle **Activate Incoming Webhooks** to On
4. Click **Add New Webhook to Workspace** and select the channel (e.g. `#infra-alerts`)
5. Copy the Webhook URL and add it to `.env`:

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
```

---

## 8. GitHub Secrets for CI/CD

In your GitHub repository, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Description |
|------------|-------------|
| `OPENROUTER_API_KEY_1` | First OpenRouter API key |
| `OPENROUTER_API_KEY_2` | Second OpenRouter API key |
| `OPENROUTER_API_KEY_3` | Third OpenRouter API key |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | e.g. `us-east-1` |
| `AWS_ROLE_ARN` | (Optional) IAM role ARN for OIDC auth |

---

## 9. Triggering the Workflow

### Automatic (scheduled)

The workflow runs automatically every 6 hours via cron (`0 */6 * * *`). No action needed.

### Manual trigger

1. Go to **Actions → Terraform Drift Detection → Run workflow**
2. Optionally fill in a reason (e.g. "Post-deployment drift check")
3. Click **Run workflow**

### What to expect

- The workflow will appear under the Actions tab
- Check the **drift-detection** job logs to see each step
- If drift is found, you'll receive a Slack message within a minute or two
- The `terraform plan` artifact is uploaded for every run (even failures)

---

## 10. Simulating Drift for Testing

The easiest way to create real drift is to manually change a resource tag in the AWS console:

1. Go to **EC2 → Instances** in the AWS console
2. Find the instance created by Terraform (tagged `drift-agent-dev-app`)
3. Click **Actions → Manage tags**
4. Change the `Name` tag to something different (e.g. `drift-agent-dev-app-manual`)
5. Save the change
6. Trigger the agent manually (see section 9) or wait for the next scheduled run

Since a tag change is low-risk (score ≤ 30, level=LOW), the agent will auto-apply and revert it, then send a ✅ Slack notification.

To test the escalation path, you can temporarily open SSH to `0.0.0.0/0` on the security group — the agent will detect the dangerous pattern and send a 🚨 escalation alert.

---

## 11. Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_llm_client.py -v
pytest tests/test_terraform_client.py -v
pytest tests/test_slack_client.py -v
pytest tests/test_aws_client.py -v
pytest tests/test_nodes.py -v
pytest tests/test_graph.py -v

# Run with coverage report
pip install pytest-cov
pytest tests/ --cov=agent --cov=core --cov=config --cov-report=term-missing
```

### Expected output (all passing)

```
tests/test_llm_client.py::TestOpenRouterClientKeyRotation::test_first_key_succeeds PASSED
tests/test_llm_client.py::TestOpenRouterClientKeyRotation::test_rotates_on_429 PASSED
...
tests/test_graph.py::TestGraphLowRiskAutoApply::test_auto_remediated_status PASSED
tests/test_graph.py::TestGraphHighRiskEscalate::test_escalated_status PASSED
...
================================ 35 passed in 1.23s ================================
```

---

## 12. Using the Local Test Script

The `scripts/test_local.py` runner lets you exercise the full agent without real AWS or Terraform:

```bash
# Low-risk scenario (tag change → auto-applied)
python scripts/test_local.py --mock

# High-risk scenario (SSH opened to 0.0.0.0/0 → escalated)
python scripts/test_local.py --mock --high-risk

# Real mode (requires .env configured, Terraform initialised, AWS creds)
python scripts/test_local.py
```

The script prints coloured terminal output showing the final state:

```
============================================================
  Self-Healing Terraform Drift Detection Agent — Local Test
============================================================
  Mode: MOCK
  Scenario: LOW RISK

============================================================
  Final Agent State
============================================================

  Status:         AUTO_REMEDIATED
  Timestamp:      2024-06-01T12:00:00Z
  Has Drift:      True
  Risk Score:     10/100
  Risk Level:     LOW
  Action Taken:   AUTO_APPLY
  Slack Sent:     True
  Apply Success:  True
```

---

## 13. Understanding the Risk Scoring System

| Score Range | Level | Action |
|-------------|-------|--------|
| 0 – 30 | LOW | Auto-apply (if no dangerous patterns) |
| 31 – 60 | MEDIUM | Escalate |
| 61 – 85 | HIGH | Escalate |
| 86 – 100 | CRITICAL | Escalate |

### Dangerous patterns that always trigger escalation

Regardless of the LLM's numeric score, the agent pattern-scans the raw plan output for:

- `0.0.0.0/0` — security group opened to the internet
- `::/0` — IPv6 equivalent
- `"*"` — IAM wildcard in actions or resources
- `prod` — changes to production resources
- `kms` — KMS key modifications
- `public_access` — S3 public access being enabled

If any pattern matches, the recommended action is forced to `ESCALATE` regardless of the LLM's assessment.

### Overriding the threshold

Set `RISK_AUTO_APPLY_THRESHOLD` in `.env` to change the cutoff:

```
RISK_AUTO_APPLY_THRESHOLD=20   # More conservative: fewer auto-applies
RISK_AUTO_APPLY_THRESHOLD=50   # More permissive: auto-apply medium-risk changes
```

---

## 14. Troubleshooting

### `terraform: command not found`

Install Terraform from https://developer.hashicorp.com/terraform/install and ensure it's on your `$PATH`:

```bash
which terraform
terraform version
```

### `No OpenRouter API keys configured`

Make sure `.env` is in the project root and at least `OPENROUTER_API_KEY_1` is set. Run:

```bash
python -c "from config.settings import settings; print(settings.openrouter_api_keys)"
```

### `All 3 OpenRouter API keys failed`

- Check your account at https://openrouter.ai — you may have exceeded the free-tier rate limits
- Wait a few minutes and try again
- Add credits to your account for higher rate limits

### `Error: No valid credential sources found for AWS Provider`

Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` in `.env`, or configure an AWS profile:

```bash
aws configure
```

### Slack notification not received

1. Verify `SLACK_WEBHOOK_URL` is correct in `.env`
2. Test the webhook directly:
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test from drift agent"}' \
     $SLACK_WEBHOOK_URL
   ```
3. Check your Slack channel — ensure the app is invited: `/invite @Terraform Drift Agent`

### `terraform plan` times out

Increase `TERRAFORM_TIMEOUT_PLAN` in `.env` (default: 300 seconds). Large Terraform states with many resources can take longer to plan.

### GitHub Actions: AWS authentication fails

If using OIDC, ensure your IAM role's trust policy allows the GitHub Actions OIDC provider and your repository. If using static credentials, confirm all four secrets are set correctly in the repository settings.

---

## 15. Project Structure

```
self-healing-terraform/
│
├── .github/workflows/
│   └── drift_detection.yml     # Scheduled + manual GitHub Actions workflow
│
├── agent/
│   ├── __init__.py
│   ├── graph.py                # LangGraph StateGraph: nodes, edges, routing
│   ├── nodes.py                # All 8 LangGraph node functions
│   ├── state.py                # AgentState TypedDict schema
│   └── prompts.py              # LLM system prompt and user prompt builder
│
├── core/
│   ├── __init__.py
│   ├── llm_client.py           # OpenRouter HTTP client with key rotation
│   ├── terraform_client.py     # Terraform CLI wrapper (plan, apply, parse)
│   ├── slack_client.py         # Slack Block Kit notification sender
│   └── aws_client.py           # AWS CloudTrail event fetcher
│
├── config/
│   ├── __init__.py
│   └── settings.py             # Settings dataclass: env vars + constants
│
├── terraform/
│   ├── main.tf                 # Sample AWS infrastructure (VPC, EC2, S3, IAM)
│   ├── variables.tf            # Input variables
│   ├── outputs.tf              # Output values
│   └── terraform.tfvars.example
│
├── tests/
│   ├── __init__.py
│   ├── test_llm_client.py      # Unit tests: key rotation, fence stripping
│   ├── test_terraform_client.py # Unit tests: plan/apply/parse
│   ├── test_slack_client.py    # Unit tests: Block Kit payloads
│   ├── test_aws_client.py      # Unit tests: CloudTrail lookup + format
│   ├── test_nodes.py           # Unit tests: each node in isolation
│   └── test_graph.py           # Integration tests: full graph execution
│
├── scripts/
│   └── test_local.py           # Coloured CLI runner: --mock / --high-risk
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## License

MIT — free to use, modify, and distribute with attribution.
