# =============================================================================
# WTG DLP Plugin — Azure Container Apps deployment (PowerShell)
#
# Usage (from repo root, with corporate CIDR):
#   $env:CORP_IP_CIDR = "203.0.113.0/24"
#   .\deploy\azure\deploy.ps1
#
# Prerequisites: Azure CLI (az), Docker, and an active az login session.
# =============================================================================

param(
    [string]$RG             = "wtg-dlp-rg",
    [string]$Location       = "australiaeast",
    [string]$EnvName        = "wtg-dlp-env",
    [string]$AppName        = "wtg-dlp-plugin",
    [string]$StorageAccount = "wtgdlpstorage$([int](Get-Date -UFormat %s) % 100000)",
    [string]$ShareName      = "wtg-dlp-data",
    [string]$CorpIpCidr     = $env:CORP_IP_CIDR
)

if (-not $CorpIpCidr) {
    Write-Error "Set CORP_IP_CIDR env var or pass -CorpIpCidr parameter (e.g. 203.0.113.0/24)"
    exit 1
}

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
Write-Host "`n==> [1/9] Registering Azure providers" -ForegroundColor Cyan
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

Write-Host "`n==> [2/9] Creating resource group: $RG" -ForegroundColor Cyan
az group create --name $RG --location $Location --output none

Write-Host "`n==> [3/9] Creating storage account: $StorageAccount" -ForegroundColor Cyan
az storage account create `
    --name $StorageAccount `
    --resource-group $RG `
    --location $Location `
    --sku Standard_LRS `
    --kind StorageV2 `
    --output none

$StorageKey = az storage account keys list `
    --account-name $StorageAccount `
    --resource-group $RG `
    --query "[0].value" -o tsv

Write-Host "`n==> [4/9] Creating file share: $ShareName" -ForegroundColor Cyan
az storage share create `
    --name $ShareName `
    --account-name $StorageAccount `
    --account-key $StorageKey `
    --output none

Write-Host "`n==> [5/9] Uploading DLP list CSVs" -ForegroundColor Cyan
az storage file upload-batch `
    --account-name $StorageAccount `
    --account-key $StorageKey `
    --destination "$ShareName/dlp_lists" `
    --source "config/dlp_lists/"

Write-Host "`n==> [6/9] Creating Container Apps environment: $EnvName" -ForegroundColor Cyan
az containerapp env create `
    --name $EnvName `
    --resource-group $RG `
    --location $Location `
    --output none

Write-Host "`n==> [7/9] Mounting file share in environment" -ForegroundColor Cyan
az containerapp env storage set `
    --name $EnvName `
    --resource-group $RG `
    --storage-name wtg-dlp-data `
    --azure-file-account-name $StorageAccount `
    --azure-file-account-key $StorageKey `
    --azure-file-share-name $ShareName `
    --access-mode ReadWrite `
    --output none

Write-Host "`n==> [8/9] Building and deploying Container App (this takes ~5 minutes)" -ForegroundColor Cyan
az containerapp up `
    --name $AppName `
    --resource-group $RG `
    --environment $EnvName `
    --source . `
    --ingress external `
    --target-port 8443 `
    --env-vars `
        "DLP_LIST_DIR=/app/data/dlp_lists" `
        "AUDIT_LOG_PATH=/app/data/audit/audit.ndjson"

# Attach file share volume
az containerapp update `
    --name $AppName `
    --resource-group $RG `
    --volume-mount "volumeName=dlp-data,mountPath=/app/data" `
    --volume "volumeName=dlp-data,storageType=AzureFile,storageName=wtg-dlp-data" `
    --output none

Write-Host "`n==> [9/9] Applying IP access restriction" -ForegroundColor Cyan
az containerapp ingress access-restriction set `
    --name $AppName `
    --resource-group $RG `
    --rule-name "AllowCorporate" `
    --ip-address $CorpIpCidr `
    --action Allow `
    --order 1 `
    --output none

# ---------------------------------------------------------------------------
$Fqdn = az containerapp show `
    --name $AppName `
    --resource-group $RG `
    --query "properties.configuration.ingress.fqdn" -o tsv

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Deployment complete!" -ForegroundColor Green
Write-Host "  App URL:  https://$Fqdn" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "  1. Replace AZURE_APP_FQDN in addin/manifest.xml,"
Write-Host "     addin/launchevent.js, and addin/taskpane.js with:"
Write-Host "     $Fqdn"
Write-Host ""
Write-Host "  PowerShell find-and-replace (run from repo root):"
Write-Host "  Get-ChildItem addin\manifest.xml,addin\launchevent.js,addin\taskpane.js | ForEach-Object {"
Write-Host "    (Get-Content `$_.FullName) -replace 'AZURE_APP_FQDN','$Fqdn' | Set-Content `$_.FullName"
Write-Host "  }"
Write-Host ""
Write-Host "  2. Commit, push, and re-upload manifest.xml to M365 Admin Center."
Write-Host "  3. Verify: curl https://$Fqdn/health"
Write-Host "============================================================" -ForegroundColor Green
