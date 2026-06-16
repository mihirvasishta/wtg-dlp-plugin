#!/usr/bin/env bash
# =============================================================================
# WTG DLP Plugin — Azure Container Apps one-shot deployment script
#
# Usage:
#   chmod +x deploy/azure/deploy.sh
#   CORP_IP_CIDR="203.0.113.0/24" ./deploy/azure/deploy.sh
#
# Prerequisites: Azure CLI (az), Docker, and an active az login session.
# Run from the repo root directory.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these before running
# ---------------------------------------------------------------------------
RG="${RG:-wtg-dlp-rg}"
LOCATION="${LOCATION:-australiaeast}"
ENV_NAME="${ENV_NAME:-wtg-dlp-env}"
APP_NAME="${APP_NAME:-wtg-dlp-plugin}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-wtgdlpstorage$(date +%s | tail -c 6)}"
SHARE_NAME="${SHARE_NAME:-wtg-dlp-data}"
CORP_IP_CIDR="${CORP_IP_CIDR:?Set CORP_IP_CIDR to your corporate public IP range (e.g. 203.0.113.0/24)}"

# ---------------------------------------------------------------------------
echo "==> [1/9] Registering Azure providers (safe to re-run)"
az provider register --namespace Microsoft.App       --wait
az provider register --namespace Microsoft.OperationalInsights --wait

echo "==> [2/9] Creating resource group: $RG"
az group create --name "$RG" --location "$LOCATION" --output none

echo "==> [3/9] Creating storage account: $STORAGE_ACCOUNT"
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --output none

STORAGE_KEY=$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RG" \
  --query "[0].value" -o tsv)

echo "==> [4/9] Creating file share: $SHARE_NAME"
az storage share create \
  --name "$SHARE_NAME" \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --output none

echo "==> [5/9] Uploading DLP list CSVs"
az storage file upload-batch \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --destination "$SHARE_NAME/dlp_lists" \
  --source "config/dlp_lists/"

echo "==> [6/9] Creating Container Apps environment: $ENV_NAME"
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --output none

echo "==> [7/9] Mounting file share in environment"
az containerapp env storage set \
  --name "$ENV_NAME" \
  --resource-group "$RG" \
  --storage-name wtg-dlp-data \
  --azure-file-account-name "$STORAGE_ACCOUNT" \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name "$SHARE_NAME" \
  --access-mode ReadWrite \
  --output none

echo "==> [8/9] Building and deploying Container App (this takes ~5 minutes)"
az containerapp up \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --environment "$ENV_NAME" \
  --source . \
  --ingress external \
  --target-port 8443 \
  --env-vars \
    "DLP_LIST_DIR=/app/data/dlp_lists" \
    "AUDIT_LOG_PATH=/app/data/audit/audit.ndjson"

# Attach file share volume
az containerapp update \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --volume-mount "volumeName=dlp-data,mountPath=/app/data" \
  --volume "volumeName=dlp-data,storageType=AzureFile,storageName=wtg-dlp-data" \
  --output none

echo "==> [9/9] Applying IP access restriction"
az containerapp ingress access-restriction set \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --rule-name "AllowCorporate" \
  --ip-address "$CORP_IP_CIDR" \
  --action Allow \
  --order 1 \
  --output none

# ---------------------------------------------------------------------------
FQDN=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo ""
echo "============================================================"
echo "  Deployment complete!"
echo "  App URL:  https://$FQDN"
echo ""
echo "  Next steps:"
echo "  1. Replace AZURE_APP_FQDN in addin/manifest.xml,"
echo "     addin/launchevent.js, and addin/taskpane.js with:"
echo "     $FQDN"
echo "  2. Commit, push, and re-upload manifest.xml to M365 Admin Center."
echo "  3. Verify: curl https://$FQDN/health"
echo "============================================================"
