# AzLure — Custom Log Analysis (Cheap Mode)

This pipeline ingests **Azure resource logs written to a Storage Account** (not Log Analytics), parses them, runs a few **detections**, and stores events in a local **SQLite** DB.

It’s designed to be **very cheap**:
- No Log Analytics/Sentinel needed.
- You only pay for small storage transactions & capacity.
- Run locally, as a container, or in ACI/Functions.

## What it ingests

*If you enable the included Terraform diagnostics (optional):*
- **StorageRead/StorageWrite** for the **public** and **private** storage accounts → containers like `insights-logs-storageread`.
- **KeyVault AuditEvent** → container `insights-logs-auditevent`.
- (Optional) **Activity Logs** export to storage → `insights-activity-logs` (not enabled by default).

## Detections (default rules)

- **Public credential hit**: GET of `/backup/credential` in public Storage.
- **SAS usage**: RequestUri contains `sv=` and `sig=` (bearer usage).
- **Key Vault secret read**: operation `SecretGet`.
- **Automation account read**: ARM read of `Microsoft.Automation/automationAccounts` (optional if you export activity logs).

## Quick start

1) **Install deps** (recommended in a venv):
```bash
cd azure-honeypot/log_pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt


