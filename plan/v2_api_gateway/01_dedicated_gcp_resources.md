# Step 1: Dedicated GCP resources for this repo (detailed plan)

**Status:** IN PROGRESS. Steps 1.2–1.5 implemented on branch `infra/dedicated-gcp-resources` (gate green: 141 tests, coverage 100%). Plan approved 2026-11-11. Decisions: A = `sql-planner-apigw`, B = service-level deployer, C = reuse the original app's key.
**Repo:** `jansidv99-lab/sql_planner_cicd_gcp_api_gateway` (public), copied from `jansidv99-lab/sql_planner_cicd_gcp`.
**Depends on:** v1 app, CI and CD (`plan/v1_app_development/`, all done). PR #1 (docs) should be merged first.
**Unblocks:** later API Gateway work, which needs its own deployed service in this repo.

## Goal

This repo gets **its own** CD pipeline and GCP resources in the **same GCP project**. Nothing that
belongs to the original app (or any other app in the project) is used or changed.

Today this repo's CD can't deploy (the first run on `main` failed at auth, as expected), because:
- `scripts/gcp_setup.sh` and `.github/workflows/cd.yml` still name the original repo's resources;
- the WIF provider `github-sql-planner` only accepts `jansidv99-lab/sql_planner_cicd_gcp` + `main`;
- the GitHub repo variables CD reads don't exist on this repo;
- there is no `.env` in this checkout (it's gitignored, so it didn't come along with the copy).

---

## Current GCP state (checked 2026-11-11, read-only)

Project `project-6df5979b-bc90-43d3-a79` (number `309866353676`). Your gcloud account has `roles/owner`.

| Resource type | Existing (all left untouched) |
|---|---|
| Cloud Run services (`asia-south1`) | `sql-planner` (original repo), `sql-planner-pm`, `data-analysis-script-generator`, `driver-api`, `driver-consumer` |
| Service accounts | `sql-planner-runtime`, `sql-planner-deployer`, `sql-planner-pm-runtime`, `sql-planner-pm-deployer`, `gh-deployer`, `run-runtime`, `driver-api-sa`, `driver-consumer-sa`, plus defaults |
| Artifact Registry repos | `apps`, `cloud-run-source-deploy`, `sql-planner`, `sql-planner-pm` |
| Secrets | `openai-api-key`, `sql-planner-openai-api-key`, `sql-planner-pm-openai-api-key` |
| WIF pool `github-pool` providers | `github-provider`, `github-sql-planner` (condition: original repo + `main`) |
| Project-level Run roles | `gh-deployer` → `run.admin`; `sql-planner-deployer` and `sql-planner-pm-deployer` → `run.developer` |

Note: the two existing `sql-planner*` deployers have **project-wide** `run.developer`, so each one
can deploy to *any* Cloud Run service in the project. This plan avoids that for the new deployer
(see Decision B).

---

## New resources (prefix `sql-planner-apigw`)

All names are checked as free and within GCP length limits.

| Resource | Name | Notes |
|---|---|---|
| Cloud Run service | `sql-planner-apigw` | `asia-south1`, same settings as v1 |
| Artifact Registry repo | `sql-planner-apigw` | Docker, cleanup policy: keep latest 10 |
| Secret | `sql-planner-apigw-openai-api-key` | value taken from `.env` `OPENAI_API_KEY`, never printed |
| Runtime SA | `sql-planner-apigw-runtime` | reads its own secret only; writes traces |
| Deployer SA | `sql-planner-apigw-deployer` | used by GitHub Actions through WIF; no key |
| WIF provider | `github-sql-planner-apigw` | in the existing pool `github-pool`; condition: this repo + `refs/heads/main` |
| GitHub repo variables | on `sql_planner_cicd_gcp_api_gateway` | `GCP_PROJECT_ID`, `GCP_REGION`, `WIF_PROVIDER`, `DEPLOYER_SA`, `RUNTIME_SA`, `OPENAI_BASE_URL`, `MODEL` |

The existing pool `github-pool` is reused only as a container, as v1 did. A new provider is
independent of the other providers in the pool.

---

## Decisions (approved 2026-11-11)

**A. Name prefix:** `sql-planner-apigw` ✅ chosen. It's short, matches the repo's purpose, and
leaves room for suffixes (the SA IDs have a 30-character limit). Tell me if you'd prefer another.

**B. Deployer scope:** service-level ✅ chosen.
- *Service-level (recommended):* the setup script creates the service once with Google's public
  placeholder image (`us-docker.pkg.dev/cloudrun/container/hello`) and grants
  `run.developer` **on `sql-planner-apigw` only**. The new deployer can't touch any other service.
- *Project-level (same as v1):* simpler, but the new deployer could deploy to `sql-planner`,
  `sql-planner-pm` and the other services.

**C. API key:** a new secret holding the **same** key as the original app (copied from the
original repo's `.env`), or a **separate** key so spend and rotation are tracked per app.
✅ Chosen: **reuse the original app's key** (copy `OPENAI_API_KEY` from the original repo's `.env`).

---

## Steps

### 1.1 Create `.env` in this checkout (you)
- **Purpose:** the setup script and local runs read `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`,
  `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MODEL` from it.
- **How:** copy `.env` from the original repo's folder (or fill in `.env.example`), keeping the
  original app's `OPENAI_API_KEY` (Decision C). Claude never reads or prints the key.

### 1.2 Parametrize `scripts/gcp_setup.sh` (code change)
- **Purpose:** one script that creates this repo's resources and nothing else.
- **Changes:**
  - `GITHUB_REPO="jansidv99-lab/sql_planner_cicd_gcp_api_gateway"`.
  - One `APP="sql-planner-apigw"` variable that every name is built from (service, AR repo,
    secret, both SAs, provider), with display names and descriptions to match.
  - New step that creates the Cloud Run service with the placeholder
    image if it doesn't exist (runtime SA, no public access), then binds `run.developer` on the
    service instead of the project (Decision B).
  - Header comments point to this plan doc.
- Still re-runnable: every step checks if the resource exists first.

### 1.3 Update `.github/workflows/cd.yml` (code change)
- **Purpose:** deploy to the new service, repo and secret.
- **Changes:** `SERVICE`, `AR_REPO`, `SECRET_NAME` → the `sql-planner-apigw` names; label
  `app=sql-planner-apigw`; plan link in the header comment. Everything else (WIF auth, SHA tags,
  smoke check) stays the same.
- **Dependency:** `workflow_run` uses the workflow file from `main`, so this only takes effect
  after the PR is merged.

### 1.4 Separate traces per app (small code change)
- **Purpose:** `app/observability.py` hard-codes `SERVICE_NAME = "sql-planner"`, so traces from both
  apps would carry the same `service.name` in Cloud Trace. (Logs are already separate: Cloud Run
  labels them with its own service name.)
- **Change:** use `K_SERVICE` (set by Cloud Run) when present, falling back to `"sql-planner"`
  locally. Update the two assertions in `tests/test_observability.py`. Coverage stays ≥ 90%.

### 1.5 Update CLAUDE.md (docs)
- Replace the "not yet wired up" warning with the new resource names, URL, log query
  (`service_name="sql-planner-apigw"`), rollback command, and the full list of resources that
  must never be modified (the original app's, `sql-planner-pm*`, `gh-deployer`, etc.).

### 1.6 Open a PR and wait for CI (Claude, after your OK to commit)
- Branch `infra/dedicated-gcp-resources`, quality gate + Docker smoke test must pass.
- **Don't merge yet:** merging triggers CD, which needs steps 1.7–1.8 done first.

### 1.7 Run the setup script (you, as project owner)
- `bash scripts/gcp_setup.sh` in Git Bash from the PR branch. It prints every command
  except the one that carries the secret.
- **Verify (Claude, read-only):** the new resources exist; the provider condition names this
  repo; the deployer's Run role is on the new service only (Decision B); the original
  resources are unchanged (compare against the table above).

### 1.8 Make the service public (you, once)
- `gcloud run services add-iam-policy-binding sql-planner-apigw --region asia-south1
  --member=allUsers --role=roles/run.invoker`
- Needed because CD's smoke check expects public access (v1 Phase 11 found that a private service
  returns 403). The deployer can't do this itself by design.

### 1.9 Merge the PR and verify CD (after your approval)
- CI passes on `main` → CD builds, pushes to `sql-planner-apigw`, deploys, smoke check green.
- **Verify:** open the new URL and run one request; `gcloud logging read` shows
  `chain finished` for `sql-planner-apigw`; the trace has `service.name=sql-planner-apigw`;
  the original `sql-planner` service still serves its old revision.

---

## Not changed

- The original app's resources (`sql-planner` service, repo, secret, SAs, provider
  `github-sql-planner`), all `sql-planner-pm*` resources, `gh-deployer`, `run-runtime`,
  `github-provider`, `apps`, `openai-api-key`, the `driver-*` and `data-analysis-script-generator`
  services.
- `app/` logic, prompts, Streamlit UI, CI workflow.

## Rollback

- Code: revert the PR.
- GCP (only this app's resources, if you want them gone):
  delete service `sql-planner-apigw`, AR repo `sql-planner-apigw`, secret
  `sql-planner-apigw-openai-api-key`, provider `github-sql-planner-apigw`, both
  `sql-planner-apigw-*` SAs, and the project-level `cloudtrace.agent` binding for the runtime SA.
  The exact commands will be listed in CLAUDE.md.

## Risks

- **Running the old script by mistake** would only re-apply the original app's settings
  (it's idempotent), and with the wrong `GITHUB_REPO` it would also set variables on the
  original repo. Step 1.2 replaces it, so only the new script exists in this repo.
- **Cost:** one more scale-to-zero service (max 2 instances) and a small image repository.
