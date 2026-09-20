# 🛡️ Infrastructure Drift Detection & Compliance AI Agent

> An autonomous, AI-powered agent that continuously monitors AWS infrastructure for configuration drift, assesses risk using a large language model, auto-remediates low-risk changes, and escalates critical violations to Slack with full CloudTrail audit trails — all driven by GitHub Actions on a 15-minute schedule.

---

## 🏗️ Architecture Diagram

![Architecture Diagram](https://github.com/Naveen15github/Infrastructure-Drift-Detection-Compliance-AI-Agent/blob/e15ed7558d4a5844f2d907be9b89a02239ada7f0/ad.png)
---

## 📌 Table of Contents

1. [Project Overview](#-project-overview)
2. [Tech Stack](#-tech-stack)
3. [Agent Flow](#-agent-flow-langgraph-state-machine)
4. [Project Structure](#-project-structure) 
5. [Infrastructure Setup on AWS](#-step-1--infrastructure-setup-on-aws)
6. [Configuring GitHub Secrets](#-step-2--configuring-github-secrets)
7. [GitHub Actions CI/CD Pipeline](#-step-3--github-actions-cicd-pipeline)
8. [Workflow Steps In Detail](#-step-4--workflow-steps-in-detail)
9. [Slack Alerting & CloudTrail Integration](#-step-5--slack-alerting--cloudtrail-integration)
10. [Risk Scoring System](#-risk-scoring-system)
11. [Environment Variables](#-environment-variables)
12. [Local Development & Testing](#-local-development--testing)
13. [Known Issues & Fixes](#-known-issues--fixes)
14. [Results & Outcomes](#-results--outcomes) 

---

## 🚀 Project Overview

**Project Title:** Infrastructure Drift Detection & Compliance Agent
**AWS Region:** `us-east-1`
**Language:** Python 3.11
**Orchestration:** LangGraph state machine
**LLM Provider:** Groq (`llama-3.1-8b-instant`)
**CI/CD:** GitHub Actions (scheduled every 15 minutes)

### What This Agent Does

Infrastructure drift happens when the actual state of your cloud resources diverges from what is defined in your Terraform code. This is a silent but serious problem — a manually added security group rule, an accidentally resized EC2 instance, or a misconfigured S3 bucket can go undetected for hours or days and create serious security vulnerabilities or cost overruns.

I built this agent to solve that problem autonomously. Here is exactly what it does end-to-end:

1. **Runs `terraform plan`** against the live AWS environment every 15 minutes via GitHub Actions
2. **Parses the plan output** to detect which resources have drifted (adds, changes, destroys)
3. **Sends the drift details to Groq's LLM** (`llama-3.1-8b-instant`) for an intelligent risk assessment — the model returns a risk score between 0 and 100 along with a rationale
4. **Makes an autonomous decision:** if the risk score is ≤ 30, it runs `terraform apply -auto-approve` to self-heal the infrastructure without human intervention; if the risk score is > 30 or dangerous patterns are found, it escalates
5. **Fetches CloudTrail audit logs** to identify who made the unauthorized change, when, and from where
6. **Posts a rich Slack notification** with all drift details, the LLM risk assessment, dangerous patterns found, and the full CloudTrail trail of the actor who caused the drift
 
This gives teams full visibility into infrastructure compliance without any manual monitoring effort.

---

## 🧰 Tech Stack

| Component | Technology | Version / Detail |
|---|---|---|
| Language | Python | 3.11.15 |
| Infrastructure as Code | Terraform | 1.7+ |
| Cloud Provider | AWS | us-east-1 |
| LLM / AI | Groq API | `llama-3.1-8b-instant` |
| Agent Orchestration | LangGraph | State machine with 8 nodes |
| Notifications | Slack | Incoming Webhooks (Block Kit) |
| CI/CD | GitHub Actions | Cron schedule every 15 minutes |
| Terraform State Backend | AWS S3 | Versioned + AES256 encrypted |
| Audit Logs | AWS CloudTrail | Last 24 hours lookup |
| AWS SDK | boto3 | 1.34.0 |

---

## 🔄 Agent Flow (LangGraph State Machine)

The agent is built as a directed graph using **LangGraph**, where each node is a Python function and the graph routes execution based on the state at each step.

```
START
  │
  ▼
┌─────────────────────────────┐
│  run_terraform_plan_node    │  ← Runs: terraform plan -detailed-exitcode
│                             │    Captures stdout + exit code
└─────────────┬───────────────┘
              │
     Exit 0 or 1?  ──────────────────────────────────────────┐
              │ Exit 2 (drift detected)                       │
              ▼                                               ▼
┌─────────────────────────────┐                  ┌────────────────────┐
│    parse_drift_node         │                  │   finalize_node    │  → END
│  Counts: add/change/destroy │                  │   (no drift)       │
└─────────────┬───────────────┘                  └────────────────────┘
              │
              ▼
┌─────────────────────────────┐
│    analyze_risk_node        │  ← Calls Groq LLM with plan output
│  Returns: risk_score 0-100  │    Model: llama-3.1-8b-instant
│  risk_level, rationale      │    Returns structured JSON
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│    decide_action_node       │  ← Checks risk score + dangerous patterns
│  Routes: AUTO_APPLY or      │    (0.0.0.0/0, ::/0, *, prod, kms)
│          ESCALATE           │
└──────┬──────────────┬───────┘
       │              │
  LOW RISK        HIGH RISK / DANGEROUS
  (≤30)          (>30 or patterns found)
       │              │
       ▼              ▼
┌──────────────┐  ┌──────────────────────┐
│auto_apply_   │  │ fetch_audit_logs_node│  ← CloudTrail: last 24h
│node          │  │ Who changed what?    │
│terraform     │  └──────────┬───────────┘
│apply -auto-  │             │
│approve       │             ▼
└──────┬───────┘  ┌──────────────────────┐
       │          │  escalate_node       │  ← Posts to Slack
       │          │  (Slack Block Kit)   │    with risk + audit trail
       │          └──────────┬───────────┘
       │                     │
       └──────────┬──────────┘
                  ▼
        ┌──────────────────┐
        │  finalize_node   │  → END
        └──────────────────┘
```

---

## 📁 Project Structure

```
AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent/
│
├── .github/
│   └── workflows/
│       ├── drift_detection.yml          # Main GitHub Actions workflow
│       └── SCHEDULE_ENABLED.txt         # Schedule status marker
│
├── agent/
│   ├── __init__.py
│   ├── graph.py                         # LangGraph state machine definition
│   ├── nodes.py                         # 8 node functions (plan, parse, analyze, etc.)
│   ├── state.py                         # AgentState TypedDict schema
│   └── prompts.py                       # LLM prompt templates for Groq
│
├── core/
│   ├── __init__.py
│   ├── llm_client.py                    # Groq API client wrapper
│   ├── terraform_client.py              # Terraform CLI wrapper + exit code fix
│   ├── slack_client.py                  # Slack Block Kit message sender
│   └── aws_client.py                    # CloudTrail event fetcher via boto3
│
├── config/
│   ├── __init__.py
│   └── settings.py                      # Loads all environment variables
│
├── terraform/
│   ├── main.tf                          # VPC, subnet, EC2, S3, IAM, security group
│   ├── variables.tf                     # Input variables (region, env, etc.)
│   ├── outputs.tf                       # Output values
│   ├── terraform.tfvars.example         # Example tfvars file
│   └── .terraform.lock.hcl             # Provider lock file
│
├── tests/
│   ├── test_llm_client.py               # Unit tests for Groq API integration
│   ├── test_terraform_client.py         # Unit tests for Terraform wrapper
│   ├── test_slack_client.py             # Unit tests for Slack notifications
│   ├── test_aws_client.py               # Unit tests for CloudTrail
│   ├── test_nodes.py                    # Unit tests for each node
│   └── test_graph.py                    # Integration tests for full graph
│
├── scripts/
│   └── test_local.py                    # Local test runner (--mock flag supported)
│
├── screenshots/                         # Project screenshots (used in this README)
├── .env.example                         # Environment variable template
├── requirements.txt                     # Python dependencies
├── check_runs.py                        # GitHub Actions run checker utility
├── create_test_drift.py                 # Drift simulation utility
├── monitor_schedule.py                  # Schedule verification utility
└── README.md                            # This file
```

---

## ✅ Step 1 — Infrastructure Setup on AWS

The first thing I did was define and deploy all AWS infrastructure using Terraform. The state is stored remotely in S3 so that the GitHub Actions runner can access and compare it during every run.

### Terraform Resources Deployed

| Resource | ID | Status |
|---|---|---|
| VPC | `vpc-01dd21af537025114` | ✅ Active |
| Subnet | `subnet-0bd011dd79bd7f208` | ✅ Active |
| Internet Gateway | `igw-0fa856af23b9a8c82` | ✅ Active |
| Route Table | `rtb-0c62e6046cfa374ff` | ✅ Active |
| Security Group | `sg-065cb61b64417f1a4` | ⚠️ Drift (SSH 0.0.0.0/0 added manually) |
| EC2 Instance | `i-0093b8cde7603a295` | ⚠️ Drift (t3.small vs expected t3.micro) |
| S3 App Bucket | `drift-agent-dev-app-478468758108` | ✅ Active |
| IAM Role | `drift-agent-dev-app-role` | ✅ Active |
| IAM Instance Profile | `drift-agent-dev-app-profile` | ✅ Active |

### Terraform State Backend (S3)

The Terraform state is stored remotely so that the GitHub Actions workflow can authenticate, pull the current state, and run `terraform plan` to detect drift without any local state files.

```hcl
terraform {
  backend "s3" {
    bucket  = "terraform-state-drift-agent-478468758108"
    key     = "drift-agent/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}
```

State bucket features:
- **Versioning:** Enabled (can roll back to any previous state)
- **Encryption:** AES256 server-side encryption
- **Access:** Scoped to the IAM role used by the agent

### EC2 Instance — Live in AWS Console

The screenshot below shows the `drift-agent-dev-app` EC2 instance running in `us-east-1a` with instance ID `i-0093b8cde7603a295`. At this point in the demo, the instance type had been manually changed from `t3.micro` (as defined in Terraform) to `t3.small` — a deliberate drift that the agent will detect, assess, and remediate.

![AWS EC2 Console — drift-agent-dev-app instance running](https://raw.githubusercontent.com/Naveen15github/AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent/6c78190467158c3bc2a08b34745a6376e652bc1c/screenshots/Screenshot%20(650).png)

> **What you're seeing:** The AWS EC2 Instances console showing the `drift-agent-dev-app` instance in a **Running** state with `3/3 status checks passed` in `us-east-1a`. The private IP is `10.0.1.110`, confirming it's inside the VPC subnet I provisioned with Terraform. The green banner at the top confirms that tag management is working correctly on this instance. Two other instances (`mern-stack-app` and an unnamed `t2.2xlarge`) are shown as stopped — only the drift agent instance is active for this project.

---

## 🔐 Step 2 — Configuring GitHub Secrets

Before setting up the workflow, I stored all sensitive credentials as **GitHub Actions Secrets** so that none of them are ever hardcoded in the repository. The secrets are injected as environment variables at runtime by the workflow.

### Secrets Configured

| Secret Name | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user access key for authenticating with AWS |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key for authenticating with AWS |
| `GROQ_API_KEY` | API key for Groq LLM (`llama-3.1-8b-instant`) |
| `SLACK_WEBHOOK_URL` | Incoming webhook URL for posting alerts to Slack |

### How I Set Them Up

Navigate to your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, and add each of the four secrets listed above.

**Important:** I discovered that GitHub Secrets can sometimes store trailing newlines or whitespace when pasted from a terminal. This caused `InvalidHeaderValue` errors in the AWS SDK. I added a dedicated sanitization step in the workflow (covered in Step 4) that strips all whitespace using `tr -d '[:space:]'` before the credentials are used.

![GitHub Actions Secrets Configuration — all four secrets configured](https://raw.githubusercontent.com/Naveen15github/AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent/6c78190467158c3bc2a08b34745a6376e652bc1c/screenshots/Screenshot%20(654).png)

> **What you're seeing:** The GitHub repository's **Secrets and variables → Actions** settings page. All four required secrets are configured as **Repository secrets**: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (both updated 5 minutes ago), `GROQ_API_KEY` (updated 1 hour ago), and `SLACK_WEBHOOK_URL` (updated yesterday). The secrets panel shows them as locked/masked — their values are never exposed in logs or UI, only injected into the runner environment at workflow execution time.

---

## ⚙️ Step 3 — GitHub Actions CI/CD Pipeline

The core of the automation is a GitHub Actions workflow that runs on a **15-minute cron schedule**. It can also be triggered manually via `workflow_dispatch`, which is useful for on-demand drift checks.

### Workflow File: `.github/workflows/drift_detection.yml`

```yaml
name: Terraform Drift Detection

on:
  schedule:
    - cron: "*/15 * * * *"   # Run every 15 minutes
  workflow_dispatch:           # Allow manual trigger from Actions tab

jobs:
  drift-detection:
    name: Drift Detection
    runs-on: ubuntu-latest
    env:
      AWS_REGION: us-east-1
      GROQ_MODEL: llama-3.1-8b-instant
      GROQ_BASE_URL: https://api.groq.com/openai/v1/chat/completions
      TERRAFORM_DIR: terraform
      RISK_AUTO_APPLY_THRESHOLD: 30
      CLOUDTRAIL_LOOKBACK_HOURS: 24

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Verify checkout commit
        run: |
          echo "Commit SHA: ${{ github.sha }}"
          echo "Commit message: $(git log -1 --pretty=%s)"

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Set up Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.7.0"
          terraform_wrapper: false     # CRITICAL: wrapper returns exit 0 even on drift

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Debug - Check actual AWS resources
        run: |
          echo "=== EC2 Instances ==="
          aws ec2 describe-instances --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,Tags[?Key==`Name`].Value|[0]]' --output table
          echo "=== Security Groups ==="
          aws ec2 describe-security-groups --group-ids sg-065cb61b64417f1a4 --query 'SecurityGroups[*].IpPermissions' --output json

      - name: Install Python dependencies
        run: pip install -r requirements.txt

      - name: Sanitize AWS credentials
        run: |
          CLEAN_KEY=$(echo "${{ secrets.AWS_ACCESS_KEY_ID }}" | tr -d '[:space:]')
          CLEAN_SECRET=$(echo "${{ secrets.AWS_SECRET_ACCESS_KEY }}" | tr -d '[:space:]')
          echo "AWS_ACCESS_KEY_ID=${CLEAN_KEY}" >> $GITHUB_ENV
          echo "AWS_SECRET_ACCESS_KEY=${CLEAN_SECRET}" >> $GITHUB_ENV

      - name: Debug - Check environment variables
        run: |
          echo "GROQ_API_KEY length: ${#GROQ_API_KEY}"
          echo "SLACK_WEBHOOK_URL set: $([ -n "$SLACK_WEBHOOK_URL" ] && echo YES || echo NO)"
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}

      - name: Test terraform plan exit code directly
        working-directory: terraform
        run: |
          terraform init -backend=true
          terraform plan -detailed-exitcode -out=tfplan || EXIT_CODE=$?
          echo "Exit code: ${EXIT_CODE:-0}"
        continue-on-error: true

      - name: Run drift detection agent
        run: python -m agent.graph
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}

      - name: Upload Terraform plan artifact
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: terraform-plan
          path: terraform/tfplan
          retention-days: 30
```

### GitHub Actions — Successful Run Summary

The screenshot below shows **Terraform Drift Detection #9** completing successfully in 45 seconds. The run was manually triggered using `workflow_dispatch` from the Actions tab, which is how I tested the full pipeline end-to-end before relying on the cron schedule.

![GitHub Actions Run Summary — Drift Detection #9 succeeded in 45s](https://raw.githubusercontent.com/Naveen15github/AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent/6c78190467158c3bc2a08b34745a6376e652bc1c/screenshots/Screenshot%20(653).png)

> **What you're seeing:** The GitHub Actions run summary page for **Terraform Drift Detection #9**. Key details visible:
> - **Triggered by:** `Naveen15github` manually via `workflow_dispatch`
> - **Commit:** `49fbd5c` on the `main` branch
> - **Status:** ✅ **Success**
> - **Total duration:** 45 seconds
> - **Artifacts:** 1 (the Terraform plan file, stored for 30 days)
> - **Workflow file:** `drift_detection.yml` with the `Drift Detection` job completing in 40 seconds
>
> The annotations section at the bottom shows a note about the process completing with exit code 1 — this is expected behavior from the agent deliberately exiting with a non-zero code after escalating high-risk drift to Slack (it signals that drift was found and requires attention). The Node.js 20 deprecation warning for older GitHub Actions is also visible — a non-breaking advisory.

---

## 🔬 Step 4 — Workflow Steps In Detail

The GitHub Actions job runs 12 sequential steps. Here is a breakdown of each step and why I implemented it the way I did.

![GitHub Actions Job — all 12 steps completed successfully](https://raw.githubusercontent.com/Naveen15github/AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent/6c78190467158c3bc2a08b34745a6376e652bc1c/screenshots/Screenshot%20(652).png)

> **What you're seeing:** The expanded **Drift Detection** job log in GitHub Actions showing all 12 steps completing with green checkmarks. The job ran for a total of 40 seconds. Each step's individual duration is shown on the right (e.g., "Install Python dependencies" takes 10s because it installs all packages fresh on the Ubuntu runner, "Run drift detection agent" takes 14s as it runs the full LangGraph pipeline including the Groq API call and Slack notification).

### Step-by-Step Breakdown

**Step 1 — Set up job (2s)**
The GitHub Actions runner (Ubuntu latest) is provisioned and the job environment is initialized. Job-level environment variables (`AWS_REGION`, `GROQ_MODEL`, `TERRAFORM_DIR`, etc.) are injected into the shell environment.

**Step 2 — Checkout repository (1s)**
Uses `actions/checkout@v4` to clone the repository at the triggering commit SHA into the runner's working directory. All agent code, Terraform configurations, and scripts are now available on disk.

**Step 3 — Verify checkout commit (0s)**
Prints the commit SHA and commit message to the logs for traceability. This makes it easy to correlate any drift detection run with the exact version of the agent code that executed it.

**Step 4 — Set up Python 3.11 (2s)**
Installs Python 3.11.15 using `actions/setup-python@v5` with pip caching enabled. The cache key is based on `requirements.txt`, so if dependencies haven't changed, this step is near-instant on subsequent runs.

**Step 5 — Set up Terraform (1s)**
Installs Terraform 1.7.0 using `hashicorp/setup-terraform@v3`. The critical configuration here is `terraform_wrapper: false`. By default, the Hashicorp action wraps the terraform binary so all exit codes are normalized to 0. But `terraform plan -detailed-exitcode` returns exit code 2 specifically when drift is detected. With the wrapper enabled, this is masked and drift would never be detected. Setting `terraform_wrapper: false` ensures the raw exit code propagates correctly.

**Step 6 — Configure AWS credentials (0s)**
Uses `aws-actions/configure-aws-credentials@v4` to set up AWS authentication from the GitHub Secrets. This configures the AWS CLI and SDK (boto3) for all subsequent steps.

**Step 7 — Debug: Check actual AWS resources (6s)**
Queries the live AWS environment to display the current state of EC2 instances and security group rules in the runner logs. This was added during debugging to confirm the agent is seeing the right live resources. It queries:
- All EC2 instances (instance ID, type, state, name tag)
- The specific security group (`sg-065cb61b64417f1a4`) ingress rules in JSON format

**Step 8 — Install Python dependencies (10s)**
Runs `pip install -r requirements.txt` to install the full dependency tree: `langgraph`, `langchain`, `langchain-core`, `requests`, `python-dotenv`, `boto3`, and `pytest`.

**Step 9 — Sanitize AWS credentials (0s)**
This step was added to fix a subtle but critical bug. When AWS credentials are stored in GitHub Secrets and pasted from a terminal, they sometimes contain trailing newlines or invisible whitespace characters. When Python's `boto3` sends these in HTTP Authorization headers, AWS returns a `400 InvalidHeaderFieldValue` error. This step strips all whitespace using `tr -d '[:space:]'` and re-exports clean values to `$GITHUB_ENV` so they override the original secret values for all subsequent steps.

**Step 10 — Debug: Check environment variables (0s)**
Verifies that `GROQ_API_KEY` is present and non-empty (prints its length without revealing the value) and confirms `SLACK_WEBHOOK_URL` is set. This was essential for diagnosing issues where secrets weren't being passed through to the Python process.

**Step 11 — Test terraform plan exit code directly (0s)**
Runs `terraform init` and `terraform plan -detailed-exitcode` directly in the shell (outside the Python agent) and prints the exit code. This step has `continue-on-error: true` so that even if drift is detected (exit code 2), the workflow continues to the agent step. It serves as a validation checkpoint — I can see in the logs whether Terraform itself detects drift before the Python agent processes it.

**Step 12 — Run drift detection agent (14s)**
Executes `python -m agent.graph`, which triggers the full LangGraph state machine. This is where all the intelligence lives:
- Runs Terraform plan programmatically
- Parses drift output
- Calls Groq LLM for risk assessment
- Routes to auto-apply or escalation
- Fetches CloudTrail logs
- Posts to Slack

The `GROQ_API_KEY` and `SLACK_WEBHOOK_URL` are explicitly passed in the `env:` block of this step to ensure they are available to the Python process (job-level env blocks don't always propagate to subprocess environments in all runner configurations).

---

## 🔔 Step 5 — Slack Alerting & CloudTrail Integration

The final and most visible output of the agent is the Slack notification. When the LLM risk assessment returns a score above 30 or dangerous patterns are found in the plan output, the agent skips auto-remediation and instead:

1. Queries **CloudTrail** for the last 24 hours of API events related to the drifted resources
2. Identifies **who made the change**, what action they performed, which resource they targeted, and the timestamp
3. Constructs a **rich Slack Block Kit message** with all of this context
4. Posts it to the configured Slack channel via incoming webhook

### Slack Alert — Live Notification

![Slack — Critical Infrastructure Drift Detected alert with 80/100 risk score and CloudTrail audit trail](https://raw.githubusercontent.com/Naveen15github/AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent/6c78190467158c3bc2a08b34745a6376e652bc1c/screenshots/Screenshot%20(655).png)

> **What you're seeing:** A live Slack message posted by the **Terraform Drift Agent** app to the `#all-projects` channel at **12:28 PM on June 16, 2026**. Breaking down every field in the alert:
>
> 🚨 **Critical Infrastructure Drift Detected** — The alert title immediately signals severity.
>
> **Run Timestamp:** `2026-06-16T06:58:15Z` — The exact UTC time the agent detected this drift, useful for correlating with other system events.
>
> **Risk Score: 80/100 | Risk Level: HIGH** — The Groq LLM assessed the combination of a security group rule opening `0.0.0.0/0` on port 22 (public SSH access) and an instance type change as HIGH risk with a score of 80 out of 100. This is above the auto-remediation threshold of 30, so the agent correctly escalated instead of auto-applying.
>
> **What Changed:** Shows the specific Terraform resource changes detected. The `(none)` shown here for the change summary is because the agent posted the detailed analysis inline below in the Risk Assessment section.
>
> **Risk Assessment:** *"The presence of a security group rule opening 0.0.0.0/0 on port 22 and another rule allowing 10.0.0.0/8 on port 443, as well as modifications to the instance type, pose a significant risk."* — This is the actual LLM-generated rationale from Groq's `llama-3.1-8b-instant` model. It correctly identified both the security group misconfiguration and the instance type mismatch as concerning.
>
> **Dangerous Patterns Found:** Three patterns were flagged:
> - `0.0.0.0/0` — The security group allows inbound traffic from any IP address on the internet
> - `public_access` — The resource is publicly accessible
> - `Security group rules opening 0.0.0.0/0 on sensitive ports` — Port 22 (SSH) is open to the world
> - `Changes to instance types` — The EC2 instance type was manually changed
>
> **Who Made the Change (CloudTrail):** This is the most powerful feature — the agent queries AWS CloudTrail and surfaces the full audit trail:
> - `root` performed `AuthorizeSecurityGroupIngress` on `sg-065cb61b64417f1a4` at `2026-06-15 18:29:49 UTC`
> - `Naveen` performed `RevokeSecurityGroupIngress` on `sg-065cb61b64417f1a4` at `2026-06-15 18:28:32 UTC`
> - `root` performed `AuthorizeSecurityGroupIngress` on `sg-065cb61b64417f1a4` at `2026-06-15 18:24:52 UTC`
> - `Naveen` performed `RunInstances` on `sg-065cb61b64417f1a4` at `2026-06-15 08:28:33 UTC`
> - `Naveen` performed `AuthorizeSecurityGroupIngress` on `sg-065cb61b64417f1a4` at `2026-06-15 08:28:30 UTC`
>
> This gives the on-call engineer a complete picture of *who* made changes, *when*, and *in what sequence* — directly in Slack, with no need to log into the AWS console.
>
> **Security Impact:** `Manual review required.` — The agent correctly concludes that a human must review and authorize (or revert) these changes before any automated action is taken.

### How the Slack Client Works (`core/slack_client.py`)

```python
def send_escalation_alert(drift_summary: dict, risk_assessment: dict, 
                           audit_logs: list, dangerous_patterns: list) -> bool:
    """
    Builds a Slack Block Kit message with:
    - Header with severity emoji
    - Risk score and level as colored context blocks
    - What changed (Terraform resource summary)
    - LLM risk rationale
    - Dangerous patterns as warning badges
    - CloudTrail actor list
    - Security impact summary
    - Recommended action
    """
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 Critical Infrastructure Drift Detected"
            }
        },
        # ... additional blocks for each section
    ]
    
    payload = {"blocks": blocks}
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    return response.status_code == 200
```

### How CloudTrail Integration Works (`core/aws_client.py`)

```python
def fetch_cloudtrail_events(resource_ids: list, lookback_hours: int = 24) -> list:
    """
    Queries AWS CloudTrail for API events related to the specified resources
    in the past 24 hours. Returns a list of events with:
    - username (who)
    - event_name (what action)
    - resource_name (which resource)
    - event_time (when)
    - source_ip_address (from where)
    """
    client = boto3.client("cloudtrail", region_name=AWS_REGION)
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=lookback_hours)
    
    response = client.lookup_events(
        LookupAttributes=[
            {"AttributeKey": "ResourceName", "AttributeValue": resource_id}
            for resource_id in resource_ids
        ],
        StartTime=start_time,
        EndTime=end_time,
        MaxResults=50
    )
    return response.get("Events", [])
```

---

## 📊 Risk Scoring System

### Risk Levels and Actions

| Score Range | Level | Automated Action | Example Changes |
|---|---|---|---|
| 0 – 30 | LOW | ✅ **Auto-apply** | Tag updates, name changes, minor config tweaks |
| 31 – 60 | MEDIUM | 🔔 **Escalate to Slack** | Non-critical resource modifications |
| 61 – 85 | HIGH | 🔔 **Escalate to Slack** | IAM policy changes, KMS modifications |
| 86 – 100 | CRITICAL | 🚨 **Escalate + CloudTrail** | Security group 0.0.0.0/0, production deletions |

### Dangerous Patterns (Always Escalate Regardless of Score)

The agent checks the Terraform plan output for these strings and forces escalation even if the LLM risk score is below 30:

```python
DANGEROUS_PATTERNS = [
    "0.0.0.0/0",       # Security group rule open to the entire internet
    "::/0",            # IPv6 equivalent — open to all IPv6 addresses
    '"*"',             # IAM wildcard in Action or Resource fields
    "prod",            # Any change touching a production-tagged resource
    "kms",             # KMS key modifications (encryption key changes)
    "public_access",   # S3 bucket or resource with public access enabled
]
```

### LLM Prompt Design (`agent/prompts.py`)

The system prompt is carefully engineered to make the LLM behave as a senior DevSecOps engineer and return only structured JSON — no markdown, no preamble, no explanation outside the JSON schema:

```python
SYSTEM_PROMPT = """
You are a senior DevSecOps engineer reviewing infrastructure drift in AWS.
Your job is to assess the security and operational risk of applying the detected drift.

Respond with JSON ONLY. No markdown, no preamble. Use this exact schema:
{
  "risk_score": <integer 0-100>,
  "risk_level": "LOW|MEDIUM|HIGH|CRITICAL",
  "rationale": "<one concise sentence explaining the risk>",
  "recommended_action": "AUTO_APPLY|ESCALATE"
}

Risk scoring guidelines:
- 0-30: Minor changes with no security or availability impact
- 31-60: Moderate changes requiring review but not urgent
- 61-85: Significant changes with potential security or availability impact
- 86-100: Critical changes that could expose data, break systems, or violate compliance
"""

USER_PROMPT_TEMPLATE = """
Terraform plan detected the following infrastructure drift in AWS:

{plan_output}

Assess the risk of applying this plan as-is.
"""
```

---

## 🔧 Environment Variables

### Local Development (`.env`)

Copy `.env.example` to `.env` and fill in your values:

```bash
# Groq LLM Configuration
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.1-8b-instant
GROQ_BASE_URL=https://api.groq.com/openai/v1/chat/completions

# Slack Integration
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# AWS Credentials
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_REGION=us-east-1

# Terraform Configuration
TERRAFORM_DIR=terraform
TERRAFORM_TIMEOUT_PLAN=300
TERRAFORM_TIMEOUT_APPLY=600

# Risk Thresholds
RISK_AUTO_APPLY_THRESHOLD=30

# CloudTrail
CLOUDTRAIL_LOOKBACK_HOURS=24
```

---

## 🧪 Local Development & Testing

### Prerequisites

- Python 3.11+
- Terraform 1.7+
- AWS CLI configured (`aws configure`)
- A Groq API key from [console.groq.com](https://console.groq.com/keys)
- A Slack incoming webhook URL

### Installation

```bash
# Clone the repository
git clone https://github.com/Naveen15github/AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent.git
cd AI-Powered-Infrastructure-Drift-Detection-Compliance-Agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your actual values
```

### Deploy the Terraform Infrastructure

```bash
cd terraform

# Initialize with S3 backend
terraform init

# Preview what will be created
terraform plan

# Deploy all resources
terraform apply
```

### Run the Agent Locally

```bash
# Run with mock data (no real AWS/Groq calls)
python scripts/test_local.py --mock

# Run with mock high-risk scenario
python scripts/test_local.py --mock --high-risk

# Run against real AWS (requires configured credentials and Terraform state)
python -m agent.graph
```

### Simulate Drift for Testing

```bash
# Simulate LOW-RISK drift: change instance type (auto-remediated)
aws ec2 stop-instances --instance-ids i-0093b8cde7603a295
aws ec2 modify-instance-attribute \
  --instance-id i-0093b8cde7603a295 \
  --instance-type '{"Value": "t3.small"}'
aws ec2 start-instances --instance-ids i-0093b8cde7603a295

# Simulate HIGH-RISK drift: open SSH to the entire internet (escalated)
aws ec2 authorize-security-group-ingress \
  --group-id sg-065cb61b64417f1a4 \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0
```

### Run Unit Tests

```bash
# Run all tests
pytest tests/ -v

# Run individual test files
pytest tests/test_llm_client.py -v       # Groq API integration
pytest tests/test_terraform_client.py -v # Terraform wrapper
pytest tests/test_slack_client.py -v     # Slack notifications
pytest tests/test_aws_client.py -v       # CloudTrail queries
pytest tests/test_nodes.py -v            # Individual LangGraph nodes
pytest tests/test_graph.py -v            # Full graph integration test
```

---

## 🐛 Known Issues & Fixes

### Issue 1 — Terraform Exit Code Always 0 with `setup-terraform`

**Problem:** The `hashicorp/setup-terraform@v3` action wraps the Terraform binary and normalizes all exit codes to 0, even when `terraform plan -detailed-exitcode` would normally return exit code 2 (drift detected). This meant the agent could never distinguish between "no drift" and "drift exists."

**Fix:** Set `terraform_wrapper: false` in the workflow step. Additionally, I added a fallback in `core/terraform_client.py` that parses the plan output text for the `Plan: X to add, Y to change, Z to destroy` summary line and manually sets exit code 2 if any non-zero counts are found — providing a belt-and-suspenders solution.

### Issue 2 — AWS Credentials Whitespace in GitHub Secrets

**Problem:** Pasting AWS credentials into GitHub Secrets from a terminal often includes a trailing newline. When `boto3` uses these credentials to sign HTTP requests, the Authorization header contains the whitespace, causing AWS to reject the request with `400 InvalidHeaderFieldValue`.

**Fix:** Added a dedicated "Sanitize AWS credentials" step using `tr -d '[:space:]'` to strip all whitespace and export clean values to `$GITHUB_ENV`, overriding the original secret values for all downstream steps.

### Issue 3 — GROQ_API_KEY Not Visible to Python Process

**Problem:** Environment variables set at the GitHub Actions job level are available to shell steps but sometimes not automatically propagated to subprocess environments invoked with `python -m`. The Python agent couldn't find `GROQ_API_KEY` even though it was set in the job's `env:` block.

**Fix:** Added an explicit `env:` block directly on the "Run drift detection agent" step that re-passes `GROQ_API_KEY` and `SLACK_WEBHOOK_URL` from their respective secrets. This guarantees they are available to the Python process.

### Issue 4 — OpenRouter API 404 Errors

**Problem:** The initial implementation used OpenRouter as the LLM provider. It returned persistent 404 errors and had inconsistent availability during testing.

**Fix:** Migrated entirely to **Groq API** with the `llama-3.1-8b-instant` model. Groq provides sub-second inference, a simple single-key authentication model, a clean `/v1/chat/completions` OpenAI-compatible endpoint, and significantly better reliability for this use case.

---

## 📈 Results & Outcomes

### What Was Achieved

- ✅ **Continuous drift detection** running every 15 minutes via GitHub Actions — no manual monitoring required
- ✅ **Intelligent risk classification** using Groq LLM — correctly differentiates between benign and critical changes
- ✅ **Autonomous self-healing** for low-risk drift — instance type changes, tag updates, and minor config drift are auto-remediated without human intervention
- ✅ **Actionable Slack alerts** for high-risk drift — engineers get the full picture (what changed, risk score, LLM rationale, dangerous patterns, who did it via CloudTrail) in a single notification
- ✅ **Full audit trail** via CloudTrail integration — every alert includes the actor, action, resource, and timestamp of the unauthorized change
- ✅ **Secure secret management** — all credentials managed via GitHub Secrets, never hardcoded
- ✅ **Terraform state integrity** — remote S3 backend with versioning ensures state is always consistent between runs

### Drift Scenarios Tested

| Drift Type | Risk Score | Action Taken | Result |
|---|---|---|---|
| EC2 instance type: `t3.micro` → `t3.small` | 15/100 LOW | Auto-apply | ✅ Reverted automatically |
| Security group: SSH open to `0.0.0.0/0` | 80/100 HIGH | Escalate | ✅ Slack alert sent with CloudTrail |
| Both changes together | 100/100 CRITICAL | Escalate | ✅ Slack alert with full audit trail |

---

## 📦 Python Dependencies

```
langgraph==0.0.28
langchain==0.1.0
langchain-core==0.1.0
requests==2.31.0
python-dotenv==1.0.0
boto3==1.34.0
pytest==8.0.0
pytest-mock==3.12.0
```

---

## 🔗 Resources & References

- [Groq API Documentation](https://console.groq.com/docs/quickstart)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Terraform CLI Documentation](https://developer.hashicorp.com/terraform/cli)
- [AWS CloudTrail Documentation](https://docs.aws.amazon.com/cloudtrail/)
- [GitHub Actions Encrypted Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Slack Block Kit Builder](https://app.slack.com/block-kit-builder)

---

## 👤 Author

**Naveen G**
- GitHub: [@Naveen15github](https://github.com/Naveen15github)
- AWS Account: `us-east-1`

---

*Built with ❤️ using Python, Terraform, LangGraph, Groq, and AWS.*
