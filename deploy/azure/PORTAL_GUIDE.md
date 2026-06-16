# WTG DLP Plugin — Azure Deployment via Portal (No CLI, No Docker)

Everything in this guide is done through a browser.
No Azure CLI, no Docker, no admin rights on your laptop needed.

**Time to complete:** ~30 minutes

---

## How it works

```
GitHub push → GitHub Actions builds Docker image → ghcr.io/mihirvasishta/wtg-dlp-plugin:latest
                                                          │
                                          Azure Container App pulls image
                                          HTTPS provided automatically
                                          Azure File Share stores CSVs + audit log
```

---

## Phase 1 — Let GitHub build your Docker image

### Step 1 — Push the code (the workflow file is already in the repo)

The file `.github/workflows/build-push.yml` is already committed. Every time you
`git push`, GitHub automatically builds the Docker image for you in the cloud.

If you haven't pushed since this file was added, do so now:
```powershell
git push
```

### Step 2 — Confirm the image was built

1. Open **https://github.com/mihirvasishta/wtg-dlp-plugin/actions**
2. You should see a workflow run called **"Build and push Docker image"** — wait for it to show a green ✓
3. Click the run → click the **"Print image URL"** step → confirm it shows:
   ```
   ghcr.io/mihirvasishta/wtg-dlp-plugin:latest
   ```

Your image is now ready. Azure will pull it from here — no Docker on your machine needed.

---

## Phase 2 — Create persistent storage (Azure File Share)

### Step 3 — Open the Azure Portal

Go to **https://portal.azure.com** and sign in with your Azure free account.

### Step 4 — Create a Resource Group

A resource group is a folder that holds all your Azure resources.

1. In the top search bar, type **"Resource groups"** → click it
2. Click **+ Create**
3. Fill in:
   - **Subscription:** your free account subscription
   - **Resource group name:** `wtg-dlp-rg`
   - **Region:** Australia East (or whichever is closest to you)
4. Click **Review + create** → **Create**

### Step 5 — Create a Storage Account

1. Search bar → **"Storage accounts"** → **+ Create**
2. Fill in:
   - **Resource group:** `wtg-dlp-rg`
   - **Storage account name:** `wtgdlpstorage` + 4 random digits (e.g. `wtgdlpstorage7391`) — must be globally unique, lowercase only
   - **Region:** same as your resource group
   - **Redundancy:** Locally-redundant storage (LRS) — cheapest option
3. Click **Review** → **Create** → wait ~30 seconds → **Go to resource**

### Step 6 — Create a File Share

1. In your storage account, scroll the left menu to **"File shares"** (under Data storage)
2. Click **+ File share**
3. Fill in:
   - **Name:** `wtg-dlp-data`
   - **Tier:** Transaction optimised (default)
4. Click **Create**

### Step 7 — Upload your DLP list CSV files

1. Click on the `wtg-dlp-data` file share you just created
2. Click **+ Add directory** → name it `dlp_lists` → **OK**
3. Click into the `dlp_lists` directory
4. Click **Upload** → browse to your local file:
   `...\wtg-dlp-plugin\config\dlp_lists\` and upload all `.csv` files there
5. You should see the CSV file appear in the list

### Step 8 — Copy the storage account key (you'll need it in Step 14)

1. Go back to your storage account (click its name in the breadcrumb)
2. Left menu → **"Access keys"** (under Security + networking)
3. Click **Show** next to **key1**
4. Copy the **Key** value and keep it handy (paste it into Notepad temporarily)

---

## Phase 3 — Create the Container App

### Step 9 — Create a Container Apps Environment

1. Search bar → **"Container Apps"** → **+ Create**
2. On the **Basics** tab:
   - **Resource group:** `wtg-dlp-rg`
   - **Container app name:** `wtg-dlp-plugin`
   - **Region:** same as before
3. Under **Container Apps Environment**, click **Create new**:
   - **Environment name:** `wtg-dlp-env`
   - Click **Create**
4. Don't click the main Create button yet — continue to the Container tab

### Step 10 — Set the container image

Still on the Create Container App page, click the **Container** tab:

1. Uncheck **"Use quickstart image"** if it's checked
2. Fill in:
   - **Name:** `wtg-dlp-plugin`
   - **Image source:** Other registries
   - **Image type:** Public
   - **Registry login server:** `ghcr.io`
   - **Image and tag:** `mihirvasishta/wtg-dlp-plugin:latest`
3. **CPU and memory:** `0.5 CPU, 1 Gi memory` (sufficient for this workload)

### Step 11 — Set environment variables

Still on the Container tab, scroll down to **Environment variables**. Click **+ Add** for each:

| Name | Value |
|---|---|
| `DLP_LIST_DIR` | `/app/data/dlp_lists` |
| `AUDIT_LOG_PATH` | `/app/data/audit/audit.ndjson` |

### Step 12 — Configure ingress (HTTPS)

Click the **Ingress** tab:

1. Check **Enabled**
2. **Ingress traffic:** Accepting traffic from anywhere
3. **Target port:** `8443`

Click **Review + create** → **Create**. Wait ~3 minutes.

### Step 13 — Get your app URL (AZURE_APP_FQDN)

1. Once deployed, click **Go to resource**
2. On the Overview page, find **Application Url** — it looks like:
   ```
   https://wtg-dlp-plugin.abcdef123.australiaeast.azurecontainerapps.io
   ```
3. Copy everything **after** `https://` — this is your **AZURE_APP_FQDN**

Quick test — open the health check URL in your browser:
```
https://YOUR_FQDN/health
```
You should see: `{"status":"ok"}`

---

## Phase 4 — Mount the File Share (persistent storage)

### Step 14 — Add the storage mount

The container needs to read your CSV files and write the audit log to the File Share.

1. In your Container App, left menu → **Volumes** → **+ Add**
2. Fill in:
   - **Volume type:** Azure file volume
   - **Name:** `dlp-data`
   - **Storage account:** your storage account (`wtgdlpstorage7391`)
   - **Azure file share:** `wtg-dlp-data`
   - **Storage account key:** paste the key you copied in Step 8
3. Click **Add**

4. Now go to left menu → **Containers** → click **Edit and deploy** → click your container name
5. Scroll to **Volume mounts** → **+ Add volume mount**:
   - **Volume name:** `dlp-data`
   - **Mount path:** `/app/data`
6. Click **Save** → **Create** (this triggers a new revision)

### Step 15 — Verify the File Share is working

Open in your browser:
```
https://YOUR_FQDN/debug/info
```

You should see `"dlp_dir_exists": true` and your CSV files listed under `"csv_files_found"`.

If `dlp_dir_exists` is false, check that the volume was mounted correctly (Step 14).

---

## Phase 5 — Restrict access to corporate network only

### Step 16 — Add IP restriction

1. In your Container App, left menu → **Ingress** → scroll down to **IP Security Restrictions**
2. Click **+ Add**:
   - **Rule name:** `AllowCorporate`
   - **Action:** Allow
   - **IP address range:** your corporate public IP in CIDR (e.g. `203.0.113.45/32`)
     - Find your IP at **https://whatismyip.com** from a corporate device
3. Click **Add** → **Save**

> After saving, only requests from your corporate IP will be accepted.
> All other IPs receive a 403 Forbidden response.

To add VPN or other office IPs later, repeat this step.

---

## Phase 6 — Update the add-in to use your Azure URL

### Step 17 — Find and replace AZURE_APP_FQDN in the 3 files

Open PowerShell in the project folder and run (replace with your actual FQDN):

```powershell
$fqdn = "wtg-dlp-plugin.abcdef123.australiaeast.azurecontainerapps.io"   # ← paste yours

Get-ChildItem addin\manifest.xml, addin\launchevent.js, addin\taskpane.js | ForEach-Object {
    (Get-Content $_.FullName) -replace "AZURE_APP_FQDN", $fqdn |
    Set-Content $_.FullName -Encoding UTF8
}

# Verify — this should return nothing (means all replaced)
Select-String "AZURE_APP_FQDN" addin\manifest.xml
```

### Step 18 — Commit and push

```powershell
git add addin\manifest.xml addin\launchevent.js addin\taskpane.js
git commit -m "config: set Azure Container Apps URL"
git push
```

### Step 19 — Re-upload manifest to M365 Admin Center

1. Go to **https://admin.microsoft.com** → **Settings** → **Integrated apps**
2. Find **WTG DLP Check** → **Update** (or remove + re-add)
3. Upload the updated `addin\manifest.xml`
4. Deploy

---

## Phase 7 — Final verification

### Step 20 — Send a test email

1. Open **https://outlook.office.com** as the test shared mailbox user
2. Compose From the shared mailbox → To: `test@unknowncorp.com` → Subject: `Test` → Send
3. ✅ Smart Alerts dialog should appear — same behaviour as Railway, now on Azure

### Step 21 — Check the audit log

Open in your browser:
```
https://YOUR_FQDN/debug/audit
```
After sending a test email, an entry should appear here.

---

## Ongoing: Updating DLP list CSVs

No redeployment needed — just upload a new CSV to the File Share:

1. Azure Portal → Storage accounts → your account → File shares → `wtg-dlp-data` → `dlp_lists`
2. Click **Upload** → select your updated CSV → **Upload**

The backend re-reads the file on the next request automatically.

---

## Redeploying after code changes

Every `git push` to master triggers the GitHub Actions workflow, which rebuilds the image.

After the build completes (check the Actions tab on GitHub), go to your Container App in the Portal:
1. Left menu → **Revisions and replicas** → **Create new revision**
2. Leave everything as-is → **Create**

This pulls the latest `ghcr.io/mihirvasishta/wtg-dlp-plugin:latest` image.

---

## Cost summary (free account)

| Resource | Tier | Monthly cost |
|---|---|---|
| Container App (light DLP workload) | Consumption | ~$0 |
| Azure File Share (<10 MB) | LRS | <$0.10 |
| Log Analytics (first 5 GB free) | Pay-as-you-go | $0 |
| GitHub Actions (public repo) | Free | $0 |
| GitHub Container Registry (public image) | Free | $0 |
| **Total** | | **~$0.10** |
