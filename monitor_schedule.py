"""Continuously monitor for scheduled workflow runs."""

import requests
import time
from datetime import datetime

def monitor_runs():
    """Monitor GitHub Actions runs and alert when scheduled runs start."""
    
    repo = "Naveen15github/terraform-agent-"
    workflow_file = "drift_detection.yml"
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/runs"
    
    print("=" * 80)
    print("🔍 Monitoring GitHub Actions Scheduled Runs")
    print("=" * 80)
    print(f"Repository: {repo}")
    print(f"Checking every 60 seconds...")
    print(f"Press Ctrl+C to stop\n")
    
    last_run_count = 0
    scheduled_found = False
    
    try:
        while not scheduled_found:
            try:
                response = requests.get(url, params={"per_page": 5}, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                runs = data.get('workflow_runs', [])
                scheduled_runs = [r for r in runs if r.get('event') == 'schedule']
                total_runs = len(runs)
                
                now = datetime.now().strftime("%H:%M:%S")
                
                if len(scheduled_runs) > 0:
                    print(f"\n🎉 [{now}] SUCCESS! Scheduled runs detected!")
                    print(f"   Total runs: {total_runs}")
                    print(f"   Scheduled runs: {len(scheduled_runs)}")
                    print("\n" + "=" * 80)
                    print("✅ GitHub Actions schedule is working!")
                    print("   New runs will appear every 5 minutes automatically.")
                    print("=" * 80)
                    scheduled_found = True
                    break
                
                if total_runs != last_run_count:
                    print(f"[{now}] New run detected! Total: {total_runs} (Scheduled: {len(scheduled_runs)})")
                    last_run_count = total_runs
                else:
                    print(f"[{now}] Waiting... (Total runs: {total_runs}, Scheduled: {len(scheduled_runs)})")
                
            except requests.exceptions.RequestException as e:
                print(f"[{now}] ⚠️  API error: {e}")
            
            time.sleep(60)  # Check every 60 seconds
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user.")
        print("   Run 'python check_runs.py' anytime to check status manually.")

if __name__ == "__main__":
    monitor_runs()
