#!/usr/bin/env bash
# =============================================================================
# One-time GCP + GitHub setup for CD to Cloud Run
# Plans: plan/v1_app_development/12_phase11_cd.md (original design)
#        plan/v2_api_gateway/01_dedicated_gcp_resources.md (dedicated resources for this repo)
# =============================================================================
# Creates DEDICATED resources for this repo, all named from $APP. Nothing belonging
# to other apps in the same GCP project is modified (the existing WIF pool is only
# reused as a container for a new, repo-restricted provider).
#
# Re-runnable: every step checks whether the resource already exists and skips it.
# Reads GCP_PROJECT_ID, GCP_PROJECT_NUMBER, OPENAI_API_KEY, OPENAI_BASE_URL, MODEL
# from the local .env. The API key is piped straight into Secret Manager and is
# never printed or written anywhere else.
#
# Usage (from the repo root, Git Bash):  bash scripts/gcp_setup.sh
# Requires: gcloud logged in as a project owner, gh logged in to GitHub.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

# Read a value from .env, removing optional surrounding quotes.
env_get() {
  sed -n "s/^$1=//p" .env | head -n 1 | tr -d '\r' | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'
}

[[ -f .env ]] || { echo ".env not found in the repo root"; exit 1; }

PROJECT_ID="$(env_get GCP_PROJECT_ID)"
PROJECT_NUMBER="$(env_get GCP_PROJECT_NUMBER)"
REGION="asia-south1"
GITHUB_REPO="jansidv99-lab/sql_planner_cicd_gcp_api_gateway"

APP="sql-planner-apigw"                     # every resource name below is built from this
SERVICE="$APP"                              # Cloud Run service
AR_REPO="$APP"                              # Artifact Registry repository
SECRET="${APP}-openai-api-key"              # Secret Manager secret
RUNTIME_SA_ID="${APP}-runtime"
DEPLOYER_SA_ID="${APP}-deployer"
RUNTIME_SA="${RUNTIME_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_SA="${DEPLOYER_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github-pool"                          # existing pool (reused as a container only)
PROVIDER="github-${APP}"                    # new provider, restricted to this repo + main
WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
PLACEHOLDER_IMAGE="us-docker.pkg.dev/cloudrun/container/hello"  # Google's public sample image

[[ -n "$PROJECT_ID" && -n "$PROJECT_NUMBER" ]] || { echo "GCP_PROJECT_ID/NUMBER missing in .env"; exit 1; }

export PYTHONWARNINGS=ignore   # silence gcloud's Python version notices

# Print a command, then run it (never used for commands that carry the secret value).
run() { echo "+ $*"; "$@"; }
# Like run, but retries: a just-created service account takes a few seconds to become
# usable in IAM policies ("Service account ... does not exist").
run_retry() {
  echo "+ $*"
  local i
  for i in 1 2 3 4 5 6; do
    "$@" && return 0
    echo "  not ready yet, retrying in 10s ($i/6)" >&2
    sleep 10
  done
  "$@"
}
g() { gcloud --project "$PROJECT_ID" --quiet "$@"; }
exists() { "$@" >/dev/null 2>&1; }
step() { echo; echo "=== $* ==="; }

echo "Project: $PROJECT_ID   App: $APP   GitHub repo: $GITHUB_REPO"

# --- 1. Artifact Registry repository + cleanup policy -------------------------
step "1. Artifact Registry repo '$AR_REPO' ($REGION)"
if exists g artifacts repositories describe "$AR_REPO" --location "$REGION"; then
  echo "exists, skipping create"
else
  run g artifacts repositories create "$AR_REPO" --repository-format=docker \
    --location="$REGION" --description="Images for ${GITHUB_REPO#*/} (CD)"
fi
POLICY_FILE="$(mktemp)"
cat > "$POLICY_FILE" <<'JSON'
[
  {"name": "keep-latest-10", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 10}},
  {"name": "delete-older", "action": {"type": "Delete"}, "condition": {"tagState": "any"}}
]
JSON
run g artifacts repositories set-cleanup-policies "$AR_REPO" --location="$REGION" \
  --policy="$POLICY_FILE" --no-dry-run
rm -f "$POLICY_FILE"

# --- 2. Secret with the API key (value never printed) -------------------------
step "2. Secret '$SECRET'"
if exists g secrets describe "$SECRET"; then
  echo "exists, skipping (to rotate the key: add a new version with 'gcloud secrets versions add')"
else
  [[ -n "$(env_get OPENAI_API_KEY)" ]] || { echo "OPENAI_API_KEY missing in .env"; exit 1; }
  echo "+ gcloud secrets create $SECRET --data-file=-   (value piped from .env, not shown)"
  env_get OPENAI_API_KEY | tr -d '\n' | g secrets create "$SECRET" \
    --replication-policy=automatic --data-file=- >/dev/null
fi

# --- 3. Runtime service account: reads its own secret, writes traces ----------
step "3. Runtime service account '$RUNTIME_SA_ID'"
exists g iam service-accounts describe "$RUNTIME_SA" \
  || run g iam service-accounts create "$RUNTIME_SA_ID" \
       --display-name="$APP Cloud Run runtime"
run_retry g secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor >/dev/null
# roles/cloudtrace.agent can only WRITE trace data. Logs need no role: Cloud Run
# collects the app's stdout (structured JSON) automatically.
run_retry g projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/cloudtrace.agent --condition=None >/dev/null

# --- 4. Cloud Run service (placeholder until the first CD deploy) -------------
# Created here so the deployer can be granted access to THIS service only (step 5).
# Not public: the owner opens access once, after this script (see the plan, step 1.8).
step "4. Cloud Run service '$SERVICE'"
if exists g run services describe "$SERVICE" --region "$REGION"; then
  echo "exists, skipping create"
else
  run_retry g run deploy "$SERVICE" --region "$REGION" --image "$PLACEHOLDER_IMAGE" \
    --service-account "$RUNTIME_SA" --no-allow-unauthenticated \
    --min-instances 0 --max-instances 1 --labels "app=$APP"
fi

# --- 5. Deployer service account: least privilege, this service only ----------
step "5. Deployer service account '$DEPLOYER_SA_ID'"
exists g iam service-accounts describe "$DEPLOYER_SA" \
  || run g iam service-accounts create "$DEPLOYER_SA_ID" \
       --display-name="$APP GitHub Actions deployer"
# deploy revisions of THIS service (can't change who may invoke it, can't touch other services)
run_retry g run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/run.developer >/dev/null
# push images to this app's repository only
run_retry g artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/artifactregistry.writer >/dev/null
# run the service as the runtime SA (and only that SA)
run_retry g iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/iam.serviceAccountUser >/dev/null

# --- 6. WIF provider: only this repo's main branch can deploy -----------------
step "6. Workload Identity provider '$PROVIDER'"
if exists g iam workload-identity-pools providers describe "$PROVIDER" \
     --location=global --workload-identity-pool="$POOL"; then
  echo "exists, skipping create"
else
  run g iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --location=global --workload-identity-pool="$POOL" \
    --display-name="GitHub ${APP}" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}' && assertion.ref=='refs/heads/main'"
fi
run_retry g iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}" >/dev/null

# --- 7. GitHub repository variables (none are secret) -------------------------
step "7. GitHub repository variables on $GITHUB_REPO"
setvar() { run gh variable set "$1" --repo "$GITHUB_REPO" --body "$2"; }
setvar GCP_PROJECT_ID "$PROJECT_ID"
setvar GCP_REGION "$REGION"
setvar WIF_PROVIDER "$WIF_PROVIDER"
setvar DEPLOYER_SA "$DEPLOYER_SA"
setvar RUNTIME_SA "$RUNTIME_SA"
setvar OPENAI_BASE_URL "$(env_get OPENAI_BASE_URL)"
setvar MODEL "$(env_get MODEL)"

echo
echo "Setup complete. Next (owner, once): make '$SERVICE' public:"
echo "  gcloud run services add-iam-policy-binding $SERVICE --region $REGION --member=allUsers --role=roles/run.invoker"
