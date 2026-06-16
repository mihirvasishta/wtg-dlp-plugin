# WTG DLP Plugin — Azure Deployment Troubleshooting

Issues encountered during the initial deployment to Azure Container Apps and how they were resolved.

---

## Issue 1 — GitHub Actions: Cache export not supported

**Error:**
```
ERROR: failed to build: Cache export is not supported for the docker driver.
```

**Cause:**
The `docker/build-push-action` uses GitHub Actions cache, but the default Docker driver does not
support cache export. The `docker/setup-buildx-action` step was missing from the workflow.

**Fix:**
Add `docker/setup-buildx-action@v3` as a step BEFORE the build step in `.github/workflows/build-push.yml`:

```yaml
- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3

- name: Build and push Docker image
  uses: docker/build-push-action@v5
  with:
    ...
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

---

## Issue 2 — `az storage account create`: SubscriptionNotFound

**Error:**
```
(SubscriptionNotFound) The subscription 'xxx' could not be found.
```

**Context:**
Subscription was visible and marked IsDefault=True. The error appeared when using `--location australiaeast`.

**Cause:**
The `australiaeast` region is not available on Azure free accounts (free accounts have a restricted
set of supported regions).

**Fix:**
Use `--location centralindia` (or `eastus`, `westus2`, `westeurope`). This project uses `centralindia`.

---

## Issue 3 — `az storage account create`: RequestDisallowedByPolicy

**Error:**
```
(RequestDisallowedByPolicy) Resource 'wtgdlpstorage...' was disallowed by policy.
Policy: 'Deny Storage Account Creation'
```

**Cause:**
Corporate Azure policy prohibits creating storage accounts entirely. No workaround exists within
the corporate subscription.

**Fix:**
Skip Azure File Share storage. The DLP list CSVs in `config/dlp_lists/` are already baked into the
Docker image via `COPY . .` in the Dockerfile. No persistent storage mount is needed for the prototype.

**Trade-off:**
- Updating CSVs requires a code commit + image rebuild + container update
- Audit log (`audit.ndjson`) resets if the container restarts
- Both limitations are acceptable for Phase 1 prototype

---

## Issue 4 — `az containerapp create`: UNAUTHORIZED pulling ghcr.io image

**Error:**
```
Failed to provision revision: UNAUTHORIZED: authentication required
```

**Context:**
The GitHub Container Registry package was set to **Public**, but the error persisted.

**Cause:**
Azure Container Apps has a known issue where it cannot reliably pull from `ghcr.io` even for
public images without explicit credentials. This affects consumption plan Container Apps.

**Fix:**
Pass a GitHub Personal Access Token (PAT) with `read:packages` scope:

```powershell
az containerapp create `
  --name $APP_NAME `
  --resource-group $RG `
  --environment $ENV_NAME `
  --image ghcr.io/mihirvasishta/wtg-dlp-plugin:latest `
  --registry-server "ghcr.io" `
  --registry-username "mihirvasishta" `
  --registry-password $GITHUB_PAT `
  ...
```

Create the PAT at: https://github.com/settings/tokens → Generate new token (classic) → scope: `read:packages`

---

## Issue 5 — `az containerapp ingress access-restriction set`: unrecognized argument --order

**Error:**
```
az containerapp ingress access-restriction set: error: unrecognized arguments: --order 1
```

**Cause:**
The `--order` flag was removed or is not available in the Azure CLI version installed in Cloud Shell.

**Fix:**
Omit the `--order` flag entirely. Azure assigns order automatically:

```powershell
az containerapp ingress access-restriction set `
  --name $APP_NAME `
  --resource-group $RG `
  --rule-name "AllowCorporate" `
  --ip-address $CORP_IP `
  --action Allow
```

---

## Issue 6 — Manifest upload rejected: "An XML comment cannot contain '--'"

**Error in M365 Admin Center:**
```
This app can't be installed. The manifest XML file isn't valid.
An XML comment cannot contain '--'.
```

**Cause:**
The XML spec forbids the sequence `--` inside an XML comment (`<!-- ... -->`).
The original manifest comment block contained Azure CLI flags like `--name`, `--resource-group`,
`--query` which all start with `--`.

**Fix:**
Replace any `--` sequences inside XML comments with single-dash alternatives or plain text:

```xml
<!-- Before (INVALID):
  az containerapp show --name wtg-dlp-plugin --resource-group wtg-dlp-rg
-->

<!-- After (valid): -->
<!--
  WTG DLP Plugin - Outlook Add-in Manifest
  Backend: https://wtg-dlp-plugin.lemonhill-d4c8d24d.centralindia.azurecontainerapps.io
-->
```

---

## Issue 7 — TC-002 failed: ERR_NAME_NOT_RESOLVED / DLP_BACKEND_URL contains literal "AZURE_APP_FQDN"

**Error in OWA DevTools console:**
```
POST https://azure_app_fqdn/api/dlp/check net::ERR_NAME_NOT_RESOLVED
[WTG DLP] Backend unreachable — failing open: TypeError: Failed to fetch
```

**Cause (root cause):**
The container was deployed when `launchevent.js` still had the placeholder `AZURE_APP_FQDN` as a
literal string (the URL was never replaced before building the image). Azure caches the `latest`
image tag, so `az containerapp update` did NOT pull the newer rebuilt image — it kept serving the
old version with the unresolved placeholder.

**Diagnosis steps:**
1. Open browser → navigate to `https://YOUR_FQDN/addin/launchevent.js`
2. Check whether `DLP_BACKEND_URL` contains `AZURE_APP_FQDN` literally — confirms the old image

**Fix (permanent):**
Remove all hardcoded backend URLs from the JS files. Derive the backend origin dynamically at runtime.

`addin/launchevent.js` — replace hardcoded URL lines with:
```javascript
var _backendOrigin = (function () {
  try {
    // document.currentScript.src = "https://YOUR-SERVER/addin/launchevent.js"
    return new URL(document.currentScript.src).origin;
  } catch (e) {
    return window.location.origin;
  }
}());

var DLP_BACKEND_URL   = _backendOrigin + "/api/dlp/check";
var AUDIT_BACKEND_URL = _backendOrigin + "/api/audit/log";
```

`addin/taskpane.js` — replace hardcoded audit URL with:
```javascript
var AUDIT_BACKEND_URL = window.location.origin + "/api/audit/log";
```

**Result:**
- The add-in always calls the server it was loaded from
- No URL substitution step needed in launchevent.js or taskpane.js
- `manifest.xml` is the only file that needs the actual FQDN

**To force Azure to pull a freshly rebuilt image** (when using `latest` tag):
```powershell
az containerapp update `
  --name wtg-dlp-plugin `
  --resource-group wtg-dlp-rg `
  --image ghcr.io/mihirvasishta/wtg-dlp-plugin:latest `
  --output none
```

Then verify the new JS is live by browsing to `/addin/launchevent.js` and confirming it shows
`_backendOrigin` rather than a hardcoded URL.

---

## Verification Checklist

After deployment, check each of these before testing in OWA:

| Check | Command / URL | Expected result |
|---|---|---|
| Container is running | Azure Portal → Container App → Revisions | Status: Active |
| Health endpoint | `https://FQDN/health` | `{"status":"ok"}` |
| JS served correctly | `https://FQDN/addin/launchevent.js` | Shows `_backendOrigin` block, no `AZURE_APP_FQDN` |
| DLP list loaded | `https://FQDN/debug/info` | `dlp_dir_exists: true`, CSV files listed |
| Manifest valid | M365 Admin Center | No validation errors on upload |
| Add-in deployed | OWA compose window | "DLP Violations" button visible in ribbon |
