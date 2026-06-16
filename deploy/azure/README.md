# WTG DLP Plugin — Azure Container Apps Deployment

Host the DLP backend on Azure Container Apps (free-tier compatible).
Azure provides HTTPS automatically — no certificates to manage.

---

## Architecture

```
[Analyst browser — OWA add-in JS]
    │  fetch() → https://<app>.azurecontainerapps.io/api/dlp/check
    ▼
[Azure Container Apps — consumption plan]
    │  Dockerfile (unchanged)
    │  TLS terminated by Azure ingress (app runs plain HTTP on port 8443)
    │  IP access restriction: allow corporate CIDR only
    ▼
[Azure File Share — mounted at /app/data]
    ├── dlp_lists/<mailbox>.csv   (DLP partner lists — persistent across redeployments)
    └── audit/audit.ndjson        (audit log — persistent across redeployments)
```

---

## Prerequisites

1. **Azure CLI** — https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
   ```bash
   az --version   # must be 2.55.0 or later
   ```

2. **Docker** — https://docs.docker.com/get-docker/
   (only needed if building locally; `az containerapp up --source .` can build in Azure)

3. **Azure account** — log in:
   ```bash
   az login
   az account show   # confirms your subscription
   ```

4. **Register required providers** (one-time per subscription):
   ```bash
   az provider register --namespace Microsoft.App
   az provider register --namespace Microsoft.OperationalInsights
   ```
   Wait ~2 minutes, then check: `az provider show --namespace Microsoft.App --query registrationState`

---

## Step 1 — Set Variables

Edit these before running any commands. Keep them set in your terminal for the entire session.

```bash
# Resource identifiers
RG="wtg-dlp-rg"
LOCATION="australiaeast"          # change to your preferred region
ENV_NAME="wtg-dlp-env"
APP_NAME="wtg-dlp-plugin"

# Storage (name must be globally unique, 3-24 chars, lowercase letters + numbers only)
STORAGE_ACCOUNT="wtgdlpstorage$(date +%s | tail -c 5)"   # auto-suffix for uniqueness
SHARE_NAME="wtg-dlp-data"

# Access restriction — WiseTech corporate public egress IP(s) in CIDR notation
# Find your corporate IP: https://whatismyip.com
# Example: CORP_IP_CIDR="203.0.113.0/24"
CORP_IP_CIDR="YOUR_CORPORATE_CIDR_HERE"
```

---

## Step 2 — Create Resource Group

```bash
az group create --name $RG --location $LOCATION
```

---

## Step 3 — Create Azure File Share (persistent storage)

```bash
# Create storage account
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RG \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2

# Get the storage key
STORAGE_KEY=$(az storage account keys list \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RG \
  --query "[0].value" -o tsv)

# Create the file share
az storage share create \
  --name $SHARE_NAME \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY
```

---

## Step 4 — Upload DLP List CSVs

Run from the repo root:

```bash
az storage file upload-batch \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --destination "$SHARE_NAME/dlp_lists" \
  --source "config/dlp_lists/"
```

Verify:
```bash
az storage file list \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --share-name $SHARE_NAME \
  --path "dlp_lists"
```

---

## Step 5 — Create Container Apps Environment

```bash
az containerapp env create \
  --name $ENV_NAME \
  --resource-group $RG \
  --location $LOCATION
```

This also auto-creates a Log Analytics workspace for logs.

---

## Step 6 — Mount the File Share in the Environment

```bash
az containerapp env storage set \
  --name $ENV_NAME \
  --resource-group $RG \
  --storage-name wtg-dlp-data \
  --azure-file-account-name $STORAGE_ACCOUNT \
  --azure-file-account-key $STORAGE_KEY \
  --azure-file-share-name $SHARE_NAME \
  --access-mode ReadWrite
```

---

## Step 7 — Build and Deploy the Container App

Run from the **repo root** (where the Dockerfile is):

```bash
az containerapp up \
  --name $APP_NAME \
  --resource-group $RG \
  --environment $ENV_NAME \
  --source . \
  --ingress external \
  --target-port 8443 \
  --env-vars \
    "DLP_LIST_DIR=/app/data/dlp_lists" \
    "AUDIT_LOG_PATH=/app/data/audit/audit.ndjson"
```

`az containerapp up --source .` auto-detects the Dockerfile, creates an Azure Container Registry,
builds and pushes the image, then deploys — no separate `docker build/push` step needed.

This takes 3-5 minutes on the first run.

---

## Step 8 — Attach the File Share Volume

```bash
az containerapp update \
  --name $APP_NAME \
  --resource-group $RG \
  --volume-mount "volumeName=dlp-data,mountPath=/app/data" \
  --volume "volumeName=dlp-data,storageType=AzureFile,storageName=wtg-dlp-data"
```

---

## Step 9 — Get the App URL (AZURE_APP_FQDN)

```bash
AZURE_APP_FQDN=$(az containerapp show \
  --name $APP_NAME \
  --resource-group $RG \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo "Your app URL: https://$AZURE_APP_FQDN"
```

Example output:
```
https://wtg-dlp-plugin.abcdef123456.australiaeast.azurecontainerapps.io
```

**Save this URL** — you'll need to substitute it in 3 files (Step 11).

---

## Step 10 — Restrict Access to Corporate Network Only

```bash
# Allow corporate network; all other IPs are denied automatically
az containerapp ingress access-restriction set \
  --name $APP_NAME \
  --resource-group $RG \
  --rule-name "AllowCorporate" \
  --ip-address $CORP_IP_CIDR \
  --action Allow \
  --order 1
```

To add additional IP ranges (e.g. a second office or VPN exit):
```bash
az containerapp ingress access-restriction set \
  --name $APP_NAME --resource-group $RG \
  --rule-name "AllowVPN" \
  --ip-address "198.51.100.0/24" \
  --action Allow \
  --order 2
```

To list current rules:
```bash
az containerapp ingress access-restriction list \
  --name $APP_NAME --resource-group $RG -o table
```

---

## Step 11 — Update manifest.xml and JS Files

Do a global find-and-replace of `AZURE_APP_FQDN` (without `https://`) in these 3 files:

| File | What changes |
|---|---|
| `addin/manifest.xml` | 8 URL occurrences |
| `addin/launchevent.js` | DLP_BACKEND_URL and AUDIT_BACKEND_URL |
| `addin/taskpane.js` | AUDIT_BACKEND_URL |

Example (PowerShell, run from repo root):
```powershell
$fqdn = "wtg-dlp-plugin.abcdef123456.australiaeast.azurecontainerapps.io"

Get-ChildItem addin\manifest.xml, addin\launchevent.js, addin\taskpane.js | ForEach-Object {
    (Get-Content $_.FullName) -replace "AZURE_APP_FQDN", $fqdn | Set-Content $_.FullName
}
```

After editing:
1. Commit and push to git
2. Re-upload `addin/manifest.xml` to M365 Admin Center → Integrated Apps → update the existing app

---

## Step 12 — Verify

```bash
# Health check
curl https://$AZURE_APP_FQDN/health
# Expected: {"status":"ok"}

# Confirm DLP list files are visible
curl https://$AZURE_APP_FQDN/debug/info
# Expected: dlp_dir_exists: true, csv_files_found: [...]

# Check audit log
curl https://$AZURE_APP_FQDN/debug/audit
```

Then send a TC-002 test email from OWA → Smart Alerts dialog should appear.

---

## Ongoing Operations

### Updating DLP list CSVs (no redeployment needed)

```bash
az storage file upload \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --share-name $SHARE_NAME \
  --source "config/dlp_lists/<mailbox>.csv" \
  --path "dlp_lists/<mailbox>.csv"
```

CSVDLPSource re-reads the file on the next request (mtime-based cache invalidation).

### Redeploying after code changes

```bash
# From repo root
az containerapp up --name $APP_NAME --resource-group $RG --source .
```

The File Share mount, env vars, and IP restrictions are preserved across redeployments.

### Viewing logs

```bash
az containerapp logs show \
  --name $APP_NAME \
  --resource-group $RG \
  --follow
```

### Downloading the full audit log

```bash
az storage file download \
  --account-name $STORAGE_ACCOUNT \
  --account-key $STORAGE_KEY \
  --share-name $SHARE_NAME \
  --path "audit/audit.ndjson" \
  --dest "./audit.ndjson"
```

---

## Cost Summary (Free Account)

| Resource | Tier | Est. monthly cost |
|---|---|---|
| Container Apps Environment | Consumption | $0 (first 180k vCPU-s free) |
| Container App | Consumption | $0 for light DLP workload |
| Azure Container Registry | Basic (auto-created) | ~$5 |
| Azure File Share (<10 MB) | LRS | <$0.10 |
| Log Analytics (first 5 GB) | Pay-as-you-go | $0 |

To avoid the ~$5 ACR cost, delete the auto-created registry after deployment and use
`az containerapp registry set` to point to a free GitHub Container Registry (ghcr.io) instead.
