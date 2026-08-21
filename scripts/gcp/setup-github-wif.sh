#!/usr/bin/env bash
# One-time Workload Identity Federation for GitHub Actions → Cloud Run.
# Run from a laptop already logged into gcloud on project cinetrace-ai.
# Does not print keys. Does not write a service-account JSON file.
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-cinetrace-ai}"
REGION="${GCP_REGION:-us-central1}"
POOL_ID="${GCP_WIF_POOL:-github}"
PROVIDER_ID="${GCP_WIF_PROVIDER:-github}"
SA_ID="${GCP_DEPLOY_SA:-cinetrace-github-deploy}"
GITHUB_REPO="${GITHUB_REPO:-asaf-avron/cinetrace-ai}"
SA_EMAIL="${SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud_bin() {
  if command -v gcloud >/dev/null 2>&1; then
    command -v gcloud
    return
  fi
  if command -v gcloud.cmd >/dev/null 2>&1; then
    command -v gcloud.cmd
    return
  fi
  echo "ERROR: gcloud is not on PATH" >&2
  exit 1
}

GCLOUD="$(gcloud_bin)"

echo "Using gcloud: $GCLOUD"
echo "Project: $PROJECT_ID  repo: $GITHUB_REPO"

"$GCLOUD" config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$("$GCLOUD" projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="$("$GCLOUD" iam service-accounts list --project="$PROJECT_ID" --filter="email:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" --format='value(email)')"
if [ -z "$RUNTIME_SA" ]; then
  RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

echo "Project number: $PROJECT_NUMBER"
echo "Cloud Run runtime SA: $RUNTIME_SA"

"$GCLOUD" services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  iam.googleapis.com \
  --project="$PROJECT_ID"

if ! "$GCLOUD" iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
  "$GCLOUD" iam service-accounts create "$SA_ID" \
    --project="$PROJECT_ID" \
    --display-name="GitHub Actions Cloud Run deploy"
  echo "created service account $SA_EMAIL"
else
  echo "service account exists: $SA_EMAIL"
fi

for ROLE in \
  roles/run.admin \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.admin; do
  "$GCLOUD" projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE" \
    --condition=None \
    --quiet >/dev/null
  echo "granted $ROLE on project"
done

"$GCLOUD" iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" \
  --quiet >/dev/null
echo "granted roles/iam.serviceAccountUser on $RUNTIME_SA"

if ! "$GCLOUD" iam workload-identity-pools describe "$POOL_ID" \
  --project="$PROJECT_ID" --location=global >/dev/null 2>&1; then
  "$GCLOUD" iam workload-identity-pools create "$POOL_ID" \
    --project="$PROJECT_ID" \
    --location=global \
    --display-name="GitHub Actions"
  echo "created WIF pool $POOL_ID"
else
  echo "WIF pool exists: $POOL_ID"
fi

POOL_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"
PROVIDER_NAME="${POOL_NAME}/providers/${PROVIDER_ID}"

if ! "$GCLOUD" iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --project="$PROJECT_ID" --location=global --workload-identity-pool="$POOL_ID" >/dev/null 2>&1; then
  "$GCLOUD" iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --project="$PROJECT_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" \
    --display-name="GitHub" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
  echo "created WIF provider $PROVIDER_ID"
else
  "$GCLOUD" iam workload-identity-pools providers update-oidc "$PROVIDER_ID" \
    --project="$PROJECT_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
    --quiet
  echo "updated WIF provider $PROVIDER_ID"
fi

MEMBER="principalSet://iam.googleapis.com/${POOL_NAME}/attribute.repository/${GITHUB_REPO}"
"$GCLOUD" iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="$MEMBER" \
  --quiet >/dev/null
echo "bound GitHub repo ${GITHUB_REPO} as workloadIdentityUser on $SA_EMAIL"

echo
echo "Set these GitHub Actions variables (not secrets) on ${GITHUB_REPO}:"
echo "  GCP_WORKLOAD_IDENTITY_PROVIDER=${PROVIDER_NAME}"
echo "  GCP_SERVICE_ACCOUNT=${SA_EMAIL}"
echo
echo "Example:"
echo "  gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo ${GITHUB_REPO} --body '${PROVIDER_NAME}'"
echo "  gh variable set GCP_SERVICE_ACCOUNT --repo ${GITHUB_REPO} --body '${SA_EMAIL}'"
echo
echo "No service-account JSON was created. Do not put GCP keys on Oracle or in Paperclip."
