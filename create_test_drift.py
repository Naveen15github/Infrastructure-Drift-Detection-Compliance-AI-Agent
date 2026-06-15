"""Helper script to create test drift in AWS for testing the drift detection system."""

import os
import boto3
from dotenv import load_dotenv

load_dotenv()

def create_low_risk_drift():
    """Modify an EC2 instance tag to create low-risk drift."""
    print("=" * 60)
    print("Creating LOW-RISK Drift (Tag Modification)")
    print("=" * 60)
    
    instance_id = "i-0093b8cde7603a295"
    region = os.getenv("AWS_REGION", "us-east-1")
    
    ec2 = boto3.client("ec2", region_name=region)
    
    print(f"\nInstance ID: {instance_id}")
    print("Action: Modifying the 'Name' tag")
    
    # Get current tags
    response = ec2.describe_tags(
        Filters=[
            {"Name": "resource-id", "Values": [instance_id]},
            {"Name": "key", "Values": ["Name"]}
        ]
    )
    
    current_name = response['Tags'][0]['Value'] if response['Tags'] else "unknown"
    print(f"Current Name tag: {current_name}")
    
    # Modify the tag
    new_name = current_name + "-DRIFT-TEST"
    ec2.create_tags(
        Resources=[instance_id],
        Tags=[{"Key": "Name", "Value": new_name}]
    )
    
    print(f"✓ Modified Name tag to: {new_name}")
    print("\n" + "=" * 60)
    print("✅ LOW-RISK drift created!")
    print("=" * 60)
    print("\nNow run: python scripts/test_local.py")
    print("\nExpected result:")
    print("  - System detects the tag change")
    print("  - LLM scores it as LOW risk (≤30)")
    print("  - System auto-reverts the tag")
    print("  - Slack notification sent (✅ Auto-Remediated)")

def create_high_risk_drift():
    """Add a dangerous security group rule to create high-risk drift."""
    print("=" * 60)
    print("Creating HIGH-RISK Drift (SSH to 0.0.0.0/0)")
    print("=" * 60)
    
    sg_id = "sg-065cb61b64417f1a4"
    region = os.getenv("AWS_REGION", "us-east-1")
    
    ec2 = boto3.client("ec2", region_name=region)
    
    print(f"\nSecurity Group ID: {sg_id}")
    print("Action: Adding SSH rule (0.0.0.0/0)")
    
    try:
        # Add the dangerous rule
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'DRIFT TEST - DO NOT KEEP'}]
                }
            ]
        )
        
        print("✓ Added SSH rule: 0.0.0.0/0:22")
        print("\n⚠️  WARNING: This is a security risk! The agent will escalate this.")
        print("\n" + "=" * 60)
        print("🚨 HIGH-RISK drift created!")
        print("=" * 60)
        print("\nNow run: python scripts/test_local.py")
        print("\nExpected result:")
        print("  - System detects the dangerous pattern (0.0.0.0/0)")
        print("  - LLM scores it as HIGH/CRITICAL risk")
        print("  - System ESCALATES to Slack (does NOT auto-fix)")
        print("  - Slack notification includes CloudTrail logs")
        print("\n⚠️  You'll need to manually remove this rule after testing!")
        
    except ec2.exceptions.ClientError as e:
        if "already exists" in str(e):
            print("✓ Rule already exists (drift already created)")
        else:
            print(f"❌ Error: {e}")

def menu():
    """Interactive menu for creating test drift."""
    print("\n" + "=" * 60)
    print("Test Drift Creator for Self-Healing Terraform Agent")
    print("=" * 60)
    print("\n1. Create LOW-RISK drift (tag change)")
    print("2. Create HIGH-RISK drift (SSH to 0.0.0.0/0)")
    print("3. Exit")
    
    choice = input("\nSelect option (1-3): ").strip()
    
    if choice == "1":
        create_low_risk_drift()
    elif choice == "2":
        confirm = input("\n⚠️  This will open SSH to the internet. Continue? (yes/no): ").strip().lower()
        if confirm == "yes":
            create_high_risk_drift()
        else:
            print("Cancelled.")
    elif choice == "3":
        print("Exiting.")
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    menu()
