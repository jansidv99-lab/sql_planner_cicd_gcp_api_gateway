#!/usr/bin/env bash
# =============================================================================
# One-time GCP + GitHub setup for CD to Cloud Run           (Phase 11, Part A)
# Plan: plan/12_phase11_cd.md
# =============================================================================
# Creates DEDICATED resources for this app; nothing belonging to other projects
# in the same GCP project is modified (the existing WIF pool is only reused as a
# container for a new, repo-restricted provider).
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

PROJECT_ID="$(env_get GCP_PROJECT_ID)"
PROJECT_NUMBER="$(env_get GCP_PROJECT_NUMBER)"
REGION="asia-south1"
GITHUB_REPO="jansidv99-lab/sql_planner_cicd_gcp"

AR_REPO="sql-planner"                       # Artifact Registry repository
SECRET="sql-planner-openai-api-key"         # Secret Manager secret
RUNTIME_SA="sql-planner-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_SA="sql-planner-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github-pool"                          # existing pool (reused as a container only)
PROVIDER="github-sql-planner"               # new provider, restricted to this repo + main
WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"

[[ -n "$PROJECT_ID" && -n "$PROJECT_NUMBER" ]] || { echo "GCP_PROJECT_ID/NUMBER missing in .env"; exit 1; }

export PYTHONWARNINGS=ignore   # silence gcloud's Python version notices

# Print a command, then run it (never used for commands that carry the secret value).
run() { echo "+ $*"; "$@"; }
g() { gcloud --project "$PROJECT_ID" --quiet "$@"; }
exists() { "$@" >/dev/null 2>&1; }
step() { echo; echo "=== $* ==="; }

# --- 11.1 Artifact Registry repository + cleanup policy -----------------------
step "11.1 Artifact Registry repo '$AR_REPO' ($REGION)"
if exists g artifacts repositories describe "$AR_REPO" --location "$REGION"; then
  echo "exists, skipping create"
else
  run g artifacts repositories create "$AR_REPO" --repository-format=docker \
    --location="$REGION" --description="Images for sql_planner_cicd_gcp (CD, Phase 11)"
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

# --- 11.2 Secret with the API key (value never printed) -----------------------
step "11.2 Secret '$SECRET'"
if exists g secrets describe "$SECRET"; then
  echo "exists, skipping (to rotate the key: add a new version with 'gcloud secrets versions add')"
else
  [[ -n "$(env_get OPENAI_API_KEY)" ]] || { echo "OPENAI_API_KEY missing in .env"; exit 1; }
  echo "+ gcloud secrets create $SECRET --data-file=-   (value piped from .env, not shown)"
  env_get OPENAI_API_KEY | tr -d '\n' | g secrets create "$SECRET" \
    --replication-policy=automatic --data-file=- >/dev/null
fi

# --- 11.3 Runtime service account: reads its own secret only ------------------
step "11.3 Runtime service account"
exists g iam service-accounts describe "$RUNTIME_SA" \
  || run g iam service-accounts create sql-planner-runtime \
       --display-name="sql_planner Cloud Run runtime"
run g secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor >/dev/null

# --- 11.4 Deployer service account: least privilege ---------------------------
step "11.4 Deployer service account"
exists g iam service-accounts describe "$DEPLOYER_SA" \
  || run g iam service-accounts create sql-planner-deployer \
       --display-name="sql_planner GitHub Actions deployer"
# deploy revisions (can't change who may invoke the service)
run g projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/run.developer --condition=None >/dev/null
# push images to this app's repository only
run g artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/artifactregistry.writer >/dev/null
# run the service as the runtime SA (and only that SA)
run g iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/iam.serviceAccountUser >/dev/null

# --- 11.5 WIF provider: only this repo's main branch can deploy ---------------
step "11.5 Workload Identity provider '$PROVIDER'"
if exists g iam workload-identity-pools providers describe "$PROVIDER" \
     --location=global --workload-identity-pool="$POOL"; then
  echo "exists, skipping create"
else
  run g iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --location=global --workload-identity-pool="$POOL" \
    --display-name="GitHub sql_planner_cicd_gcp" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}' && assertion.ref=='refs/heads/main'"
fi
run g iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}" >/dev/null

# --- 11.6 GitHub repository variables (none are secret) -----------------------
step "11.6 GitHub repository variables"
setvar() { run gh variable set "$1" --repo "$GITHUB_REPO" --body "$2"; }
setvar GCP_PROJECT_ID "$PROJECT_ID"
setvar GCP_REGION "$REGION"
setvar WIF_PROVIDER "$WIF_PROVIDER"
setvar DEPLOYER_SA "$DEPLOYER_SA"
setvar RUNTIME_SA "$RUNTIME_SA"
setvar OPENAI_BASE_URL "$(env_get OPENAI_BASE_URL)"
setvar MODEL "$(env_get MODEL)"

# --- 12.7 Runtime SA may write traces (Phase 12) ------------------------------
# roles/cloudtrace.agent can only WRITE trace data. Logs need no role: Cloud Run
# collects the app's stdout (structured JSON) automatically.
step "12.7 Runtime service account: Cloud Trace writer"
run g projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/cloudtrace.agent --condition=None >/dev/null

echo
echo "Setup complete."
