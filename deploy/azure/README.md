# WTG DLP Plugin — Azure Container Apps Deployment

Hosts the DLP backend on Azure Container Apps (consumption plan, free tier).
Azure provides HTTPS automatically — no TLS certificates to manage.

**Deployment method used:** GitHub Actions builds the Docker image and pushes to GitHub Container
Registry (ghcr.io). Azure Container Apps pulls the pre-built image.
No local Docker installation or `az containerapp up --source .` needed.

---

## Architecture

```
git push → GitHub Actions → ghcr.io/mihirvasishta/wtg-dlp-plugin:latest
                                        │
                            Azure Container Apps pulls image
                            HTTPS terminated by Azure ingress
                            IP access restriction: corporate CIDR only
                                        │
                            DLP list CSVs baked into image
                            (config/dlp_lists/ copied via Dockerfile COPY . .)
                            Audit log written inside container
                            (resets on redeployment — use /debug/audit to export)
```

> **Note — Azure File Share not used:** Corporate Azure policy blocks storage account creation
> (`Deny Storage Account Creation`). CSVs are baked into the Docker image instead.
> To update CSVs, update the files in `config/dlp_lists/`, commit, push, and redeploy.

---

## Prerequisites

- GitHub repository: `https://github.com/mihirvasishta/wtg-dlp-plugin`
- Azure Cloud Shell (PowerShell) at `https://portal.azure.com` — already authenticated, no local CLI needed
- A GitHub Personal Access Token (PAT) with `read:packages` scope
  - Create at: https://github.com/settings/tokens → Generate new token (classic)
  - Scope: `read:packages` only

---

## Step 1 — Set Variables

Run these in Azure Cloud Shell (PowerShell). Keep the session open for all subsequent steps.

```powershell
$RG           = "wtg-dlp-rg"
$LOCATION     = "centralindia"
$ENV_NAME     = "wtg-dlp-env"
$APP_NAME     = "wtg-dlp-plugin"
$IMAGE        = "ghcr.io/mihirvasishta/wtg-dlp-plugin:latest"
$GITHUB_USER  = "mihirvasishta"
$GITHUB_PAT   = "YOUR_GITHUB_PAT_HERE"   # read:packages scope only
```

---

## Step 2 — Register Required Azure Providers (one-time per subscription)

```powershell
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

Wait ~2 minutes, then check:
```powershell
az provider show --namespace Microsoft.App --query registrationState
```

Expected output: `"Registered"`

---

## Step 3 — Create Resource Group

```powershell
az group create --name $RG --location $LOCATION
```

---

## Step 4 — Build Docker Image (GitHub Actions)

Every `git push` to master triggers the workflow at `.github/workflows/build-push.yml`.

1. Push any pending changes:
   ```
   git push
   ```
2. Open https://github.com/mihirvasishta/wtg-dlp-plugin/actions
3. Wait for the "Build and push Docker image" run to show a green ✓ (~3 minutes)
4. The image is now at: `ghcr.io/mihirvasishta/wtg-dlp-plugin:latest`

---

## Step 5 — Create Container Apps Environment

```powershell
az containerapp env create `
  --name $ENV_NAME `
  --resource-group $RG `
  --location $LOCATION
```

This also creates a Log Analytics workspace automatically (~2 minutes).

---

## Step 6 — Deploy the Container App

```powershell
az containerapp create `
  --name $APP_NAME `
  --resource-group $RG `
  --environment $ENV_NAME `
  --image $IMAGE `
  --registry-server "ghcr.io" `
  --registry-username $GITHUB_USER `
  --registry-password $GITHUB_PAT `
  --ingress "external" `
  --target-port 8443 `
  --min-replicas 0 `
  --max-replicas 1
```

> **Why PAT is required:** Azure Container Apps cannot pull from ghcr.io without credentials,
> even if the package is set to Public. This is a known Azure limitation with ghcr.io.

Wait ~2 minutes for the first revision to become active.

---

## Step 7 — Get the App URL

```powershell
$FQDN = az containerapp show `
  --name $APP_NAME `
  --resource-group $RG `
  --query "properties.configuration.ingress.fqdn" -o tsv

Write-Host "App URL: https://$FQDN"
```

Example output:
```
App URL: https://wtg-dlp-plugin.lemonhill-d4c8d24d.centralindia.azurecontainerapps.io
```

**Quick health check:**
```powershell
Invoke-WebRequest "https://$FQDN/health" | Select-Object -Expand Content
# Expected: {"status":"ok"}
```

---

## Step 8 — Update manifest.xml with the App URL

The `addin/manifest.xml` file needs the FQDN in 8 places. Run from the repo root on your local machine:

```powershell
$fqdn = "wtg-dlp-plugin.lemonhill-d4c8d24d.centralindia.azurecontainerapps.io"

(Get-Content addin\manifest.xml) -replace "AZURE_APP_FQDN", $fqdn |
  Set-Content addin\manifest.xml -Encoding UTF8
```

> **Note:** `addin/launchevent.js` and `addin/taskpane.js` do NOT need editing.
> They derive the backend URL dynamically from `document.currentScript.src` at runtime,
> so they always call the correct server regardless of where they are hosted.

Commit and push:
```powershell
git add addin\manifest.xml
git commit -m "config: set Azure Container Apps URL in manifest"
git push
```

---

## Step 9 — Deploy the Add-in to M365

1. Open https://admin.microsoft.com → **Settings** → **Integrated apps**
2. Click **Upload custom apps** → **Office Add-in**
3. Upload `addin\manifest.xml`
4. Assign to the target shared mailbox (or test user) → **Deploy**

Propagation takes 5–15 minutes. Once deployed:
- Open OWA → compose a new email from the shared mailbox → the "DLP Violations" button appears in the ribbon

---

## Step 10 — Add IP Access Restriction (internal-only access)

Find your corporate public IP at https://whatismyip.com, then run:

```powershell
$CORP_IP = "203.0.113.45/32"   # replace with your corporate IP or CIDR range

az containerapp ingress access-restriction set `
  --name $APP_NAME `
  --resource-group $RG `
  --rule-name "AllowCorporate" `
  --ip-address $CORP_IP `
  --action Allow
```

> **Note:** Omit `--order` — that flag is not available in the current Azure CLI version.

Once any Allow rule is set, all other IPs are automatically denied.

To verify:
```powershell
az containerapp ingress access-restriction list `
  --name $APP_NAME --resource-group $RG -o table
```

---

## Ongoing Operations

### Updating DLP list CSVs

Since CSVs are baked into the Docker image, update them by:

1. Edit or add files in `config/dlp_lists/`
2. Commit and push → GitHub Actions rebuilds the image (~3 minutes)
3. Pull the new image into Azure:
   ```powershell
   az containerapp update `
     --name $APP_NAME `
     --resource-group $RG `
     --image ghcr.io/mihirvasishta/wtg-dlp-plugin:latest `
     --output none
   ```

### Redeploying after code changes

Every `git push` to master rebuilds the image. After the GitHub Actions run completes:

```powershell
az containerapp update `
  --name $APP_NAME `
  --resource-group $RG `
  --image ghcr.io/mihirvasishta/wtg-dlp-plugin:latest `
  --output none
```

### Viewing live logs

```powershell
az containerapp logs show `
  --name $APP_NAME `
  --resource-group $RG `
  --follow
```

Filter for DLP-specific lines:
```powershell
az containerapp logs show `
  --name $APP_NAME `
  --resource-group $RG `
  --follow | Select-String "\[WTG DLP\]|\[dlp\]|uvicorn"
```

### Checking the audit log

```powershell
Invoke-WebRequest "https://$FQDN/debug/audit" | Select-Object -Expand Content
```

> Note: The audit log resets if the container restarts. For a persistent audit trail, either
> mount an Azure File Share (when corporate policy permits) or export the log before redeployment.

---

## Cost Summary (Free Account)

| Resource | Tier | Est. monthly cost |
|---|---|---|
| Container Apps Environment | Consumption | $0 (first 180k vCPU-seconds free) |
| Container App | Consumption | $0 for light DLP workload |
| Log Analytics Workspace | Pay-as-you-go, first 5 GB free | $0 |
| GitHub Actions (public repo) | Free | $0 |
| GitHub Container Registry (public image) | Free | $0 |
| **Total** | | **$0** |

> Azure Container Registry (~$5/month) is NOT used — the image lives in GitHub Container Registry.

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for diagnosed issues and fixes encountered during deployment.
