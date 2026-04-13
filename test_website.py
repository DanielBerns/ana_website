import requests
import json
import os
import argparse
import getpass

# --- Configuration ---
BASE_URL = "http://127.0.0.1:5000/api/v1"
ANA_API_KEY = "dev-ana-key-change-in-prod" # Must match app/config.py

# --- Helper for Console Output ---
def print_step(title, response=None):
    print(f"\n{'-'*60}")
    print(f"▶ {title}")
    if response is not None:
        print(f"Status: {response.status_code}")
        try:
            print(json.dumps(response.json(), indent=2))
        except ValueError:
            print(response.text[:200])

def main():
    # --- CLI Argument Parsing ---
    parser = argparse.ArgumentParser(description="Ana Proxy Integration Test Script")
    parser.add_argument('-u', '--username', required=True, help='The provisioned human username.')
    parser.add_argument('-p', '--password', help='The password. If omitted, you will be prompted securely.')

    args = parser.parse_args()

    human_username = args.username
    human_password = args.password

    if not human_password:
        human_password = getpass.getpass(prompt=f"Enter password for '{human_username}': ")

    print("\nStarting Ana Proxy Integration Test...")

    # ==========================================
    # 1. Human Authentication
    # ==========================================
    resp = requests.post(f"{BASE_URL}/auth/login", json={"username": human_username,"password": human_password})
    print_step("Human: Login", resp)
    if resp.status_code != 200:
        print(f"Failed to authenticate. Did you provision '{human_username}' via the CLI?")
        return

    human_token = resp.json().get("token")
    human_headers = {"Authorization": f"Bearer {human_token}"}
    ana_headers = {"Authorization": f"Bearer {ANA_API_KEY}"}

    # ==========================================
    # 2. Human Enqueues a Task
    # ==========================================
    task_payload = {
        "command_type": "analyze_telemetry",
        "parameters": {
            "station_id": "CR-01",
            "sensor": "temperature",
            "target": "frost_detection"
        }
    }
    resp = requests.post(f"{BASE_URL}/tasks", json=task_payload, headers=human_headers)
    print_step("Human: Create Task", resp)
    task_id = resp.json().get("task_id")

    # ==========================================
    # 3. Ana System Polls Pending Tasks
    # ==========================================
    resp = requests.get(f"{BASE_URL}/tasks/pending", headers=ana_headers)
    print_step("Ana: Pull Pending Tasks", resp)

    # ==========================================
    # 4. Ana Uploads a Raw Resource (Simulated Telemetry File)
    # ==========================================
    with open("dummy_telemetry.csv", "w") as f:
        f.write("timestamp,temp,humidity\n2025-06-10T03:00:00Z,-2.5,88\n")

    with open("dummy_telemetry.csv", "rb") as f:
        files = {'file': ('dummy_telemetry.csv', f, 'text/csv')}
        resp = requests.post(f"{BASE_URL}/resources", files=files, headers=ana_headers)

    print_step("Ana: Upload Resource", resp)
    resource_id = resp.json().get("resource_id")
    os.remove("dummy_telemetry.csv")

    # ==========================================
    # 5. Ana Uploads the Intelligence Report
    # ==========================================
    report_metadata = {
        "title": "Frost Anomaly Analysis - Station CR-01",
        "triggering_task_id": task_id,
        "deductions": [
            {"subject": "station_CR-01", "predicate": "experienced", "object_": "critical_frost_event"},
            {"subject": "sensor_temperature", "predicate": "registered", "object_": "-2.5C"}
        ]
    }

    with open("dummy_graph.png", "wb") as f:
        f.write(os.urandom(1024))

    with open("dummy_graph.png", "rb") as f:
        files = {'file': ('dummy_graph.png', f, 'image/png')}
        data = {'metadata': json.dumps(report_metadata)}
        resp = requests.post(f"{BASE_URL}/reports", files=files, data=data, headers=ana_headers)

    print_step("Ana: Upload Report", resp)
    os.remove("dummy_graph.png")

    # ==========================================
    # 6. Ana Updates the Task Status to COMPLETED
    # ==========================================
    status_payload = {
        "status": "COMPLETED",
        "internal_correlation_id": "evt-bus-msg-9921"
    }
    resp = requests.patch(f"{BASE_URL}/tasks/{task_id}/status", json=status_payload, headers=ana_headers)
    print_step("Ana: Update Task Status", resp)

    # ==========================================
    # 7. Human Polls Task Status (Notices it is done)
    # ==========================================
    resp = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=human_headers)
    print_step("Human: Check Task Status", resp)
    report_uri = resp.json().get("result_report_uri")

    # ==========================================
    # 8. Human Retrieves the Intelligence Report
    # ==========================================
    if report_uri:
        resp = requests.get(f"http://127.0.0.1:5000{report_uri}", headers=human_headers)
        print_step("Human: Get Report Deductions (JSON)", resp)

        resp_file = requests.get(f"http://127.0.0.1:5000{report_uri}?download_file=true", headers=human_headers)
        print_step("Human: Download Report File Attachment (Headers Only)")
        print(f"Content-Type: {resp_file.headers.get('Content-Type')}")
        print(f"Content-Length: {resp_file.headers.get('Content-Length')} bytes")

    # ==========================================
    # 9. Human Deletes the Raw Resource (Quota Management)
    # ==========================================
    if resource_id:
        resp = requests.delete(f"{BASE_URL}/resources/{resource_id}", headers=human_headers)
        print_step(f"Human: Delete Resource {resource_id}", resp)

    print(f"\n{'-'*60}\nTest Run Complete.")

if __name__ == "__main__":
    main()
