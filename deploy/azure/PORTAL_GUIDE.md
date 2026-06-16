# WTG DLP Plugin — Azure Deployment via Browser Only

Everything in this guide is done through a browser.
No Azure CLI locally, no Docker locally needed.

**Tools used:**
- https://portal.azure.com — Azure Cloud Shell (PowerShell)
- https://github.com/mihirvasishta/wtg-dlp-plugin/actions — GitHub Actions builds the image

**Time to complete:** ~30 minutes

---

## How it works

```
git push → GitHub Actions builds Docker image → ghcr.io/mihirvasishta/wtg-dlp-plugin:latest
                                                          │
                                          Azure Container App pulls image
                                          HTTPS provided automatically (no certs to manage)
                                          DLP list CSVs baked into image
```

> **Azure File Share not used:** Corporate Azure policy blocks storage account creation.
> CSVs are included in the Docker image instead. To update them, edit the CSV files,
> commit, push, and run `az containerapp update` to pull the new image.

---

## Phase 1 — Let GitHub build your Docker image

### Step 1 — Push the code

The workflow file `.github/workflows/build-push.yml` is already committed.
Every `git push` to master triggers it automatically.

```powershell
git push
```

### Step 2 — Create a GitHub PAT (Personal Access Token)

Azure needs credentials to pull from GitHub Container Registry (ghcr.io), even for public images.

1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Note: `wtg-dlp-plugin Azure pull` (or similar)
4. Expiry: 90 days (or No expiration for a service token)
5. Check **read:packages** only
6. Click **Generate token** → copy and save the token (you won't see it again)

### Step 3 — Confirm the image was built

1. Open https://github.com/mihirvasishta/wtg-dlp-plugin/actions
2. Look for **"Build and push Docker image"** with a green ✓
3. If it's running (orange dot), wait for it to finish (~3 minutes)

---

## Phase 2 — Create the Azure Container App

### Step 4 — Open Azure Cloud Shell

1. Go to https://portal.azure.com
2. Click the **Cloud Shell icon** (>_) in the top toolbar
3. Select **PowerShell** (not Bash)
4. If prompted to create storage for Cloud Shell: this is Cloud Shell's own session storage (a few KB), which is always allowed — click **Create**

### Step 5 — Set variables

Paste and run these in Cloud Shell. Replace the PAT with the token you created in Step 2.

```powershell
$RG           = "wtg-dlp-rg"
$LOCATION     = "centralindia"
$ENV_NAME     = "wtg-dlp-env"
$APP_NAME     = "wtg-dlp-plugin"
$IMAGE        = "ghcr.io/mihirvasishta/wtg-dlp-plugin:latest"
$GITHUB_USER  = "mihirvasishta"
$GITHUB_PAT   = "ghp_PASTE_YOUR_TOKEN_HERE"
```

### Step 6 — Register Azure providers (one-time)

```powershell
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

Wait ~2 minutes, then check:
```powershell
az provider show --namespace Microsoft.App --query registrationState
```
Expected: `"Registered"`

### Step 7 — Create resource group

```powershell
az group create --name $RG --location $LOCATION
```

### Step 8 — Create Container Apps Environment

```powershell
az containerapp env create `
  --name $ENV_NAME `
  --resource-group $RG `
  --location $LOCATION
```

Takes ~2 minutes. This also creates a Log Analytics workspace automatically.

### Step 9 — Deploy the Container App

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

Takes ~2 minutes.

### Step 10 — Get the app URL

```powershell
$FQDN = az containerapp show `
  --name $APP_NAME `
  --resource-group $RG `
  --query "properties.configuration.ingress.fqdn" -o tsv

Write-Host "https://$FQDN"
```

Copy this URL. Example:
```
https://wtg-dlp-plugin.lemonhill-d4c8d24d.centralindia.azurecontainerapps.io
```

### Step 11 — Health check

```powershell
Invoke-WebRequest "https://$FQDN/health" | Select-Object -Expand Content
```

Expected: `{"status":"ok"}`

If you see `{"status":"ok"}` — the backend is running.

---

## Phase 3 — Update the add-in manifest

### Step 12 — Replace the URL in manifest.xml

Run this on your local machine (not in Cloud Shell), from the repo root directory:

```powershell
$fqdn = "wtg-dlp-plugin.lemonhill-d4c8d24d.centralindia.azurecontainerapps.io"

(Get-Content addin\manifest.xml) -replace "AZURE_APP_FQDN", $fqdn |
  Set-Content addin\manifest.xml -Encoding UTF8

# Verify - should return nothing (meaning no placeholder left)
Select-String "AZURE_APP_FQDN" addin\manifest.xml
```

> `addin/launchevent.js` and `addin/taskpane.js` do NOT need editing.
> They derive the backend URL automatically from `document.currentScript.src` at runtime.

### Step 13 — Commit and push

```powershell
git add addin\manifest.xml
git commit -m "config: set Azure Container Apps URL in manifest"
git push
```

### Step 14 — Upload manifest to M365 Admin Center

1. Go to https://admin.microsoft.com → **Settings** → **Integrated apps**
2. Click **Upload custom apps** → **Office Add-in**
3. Upload `addin\manifest.xml`
4. Assign to the target shared mailbox user(s)
5. Click **Deploy**

Propagation takes 5–15 minutes.

---

## Phase 4 — Restrict access to corporate network only

### Step 15 — Add IP restriction

Run in Azure Cloud Shell. Find your corporate IP first at https://whatismyip.com from a corporate device.

```powershell
$CORP_IP = "203.0.113.45/32"   # replace with your actual corporate IP/CIDR

az containerapp ingress access-restriction set `
  --name $APP_NAME `
  --resource-group $RG `
  --rule-name "AllowCorporate" `
  --ip-address $CORP_IP `
  --action Allow
```

Note: Do NOT include `--order 1` — that flag is not supported in the current Azure CLI version.

Once any Allow rule is set, all other IP addresses receive a 403 response automatically.

To verify:
```powershell
az containerapp ingress access-restriction list `
  --name $APP_NAME --resource-group $RG -o table
```

---

## Phase 5 — Final verification

### Step 16 — Send a test email (TC-002)

1. Open https://outlook.office.com as the test shared mailbox user
2. Compose a new email From the shared mailbox
3. To: `test@unknowncorp.com`, Subject: `Test`, Body: `Test`
4. Click Send
5. ✅ A Smart Alerts dialog should appear showing an UNKNOWN_DOMAIN violation

### Step 17 — Check the audit log

```powershell
Invoke-WebRequest "https://$FQDN/debug/audit" | Select-Object -Expand Content
```

After the test email attempt, an audit entry should appear here.

---

## Ongoing: Updating DLP list CSVs

Since CSVs are baked into the image, update them like any other code change:

1. Edit or add files in `config/dlp_lists/`
2. `git add`, `git commit`, `git push` → GitHub Actions rebuilds the image
3. Wait for the green ✓ on GitHub Actions, then pull the new image:
   ```powershell
   az containerapp update `
     --name wtg-dlp-plugin `
     --resource-group wtg-dlp-rg `
     --image ghcr.io/mihirvasishta/wtg-dlp-plugin:latest `
     --output none
   ```

---

## Redeploying after code changes

Every `git push` to master rebuilds the image. After the GitHub Actions run completes (~3 min):

```powershell
az containerapp update `
  --name wtg-dlp-plugin `
  --resource-group wtg-dlp-rg `
  --image ghcr.io/mihirvasishta/wtg-dlp-plugin:latest `
  --output none
```

---

## Cost summary (free account)

| Resource | Tier | Monthly cost |
|---|---|---|
| Container Apps Environment | Consumption | $0 |
| Container App (light DLP workload) | Consumption | $0 |
| Log Analytics (first 5 GB free) | Pay-as-you-go | $0 |
| GitHub Actions (public repo) | Free | $0 |
| GitHub Container Registry (public image) | Free | $0 |
| **Total** | | **$0** |
