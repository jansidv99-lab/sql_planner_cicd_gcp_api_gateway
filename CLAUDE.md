# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

v1 (phases 0–12) is done: app, quality gate, Docker image, GitHub Actions CI, CD to Cloud Run
and logging/tracing. Status table: `plan/v1_app_development/00_master_plan.md`. v1 was built in
the original repo; this repo deploys its own copy to dedicated GCP resources
(`plan/v2_api_gateway/01_dedicated_gcp_resources.md`, done). Live (public):
https://sql-planner-apigw-lxswvdduiq-el.a.run.app
Each new body of work gets its own plan folder under `plan/` (e.g. `plan/v1_app_development/`).
Next: the LLM API gateway (`gateway/`, phases G0–G15). The current phase is in the status table
in `plan/v2_api_gateway/00_master_plan.md`; design docs (concepts, architecture, API contract, ADRs, threat model) are in `docs/gateway/`.
Python 3.11, with dependencies pinned in `requirements*.txt`.

## Architecture

`streamlit_app.py` → `app/chain.py: run(request, columns)` → Planner → Coder → Reviewer, each once.

- `app/schema.py` is the single source of truth for the `sales` table; `validate_selection` and
  `schema_for_prompt` (only the selected columns) are used by every step.
- `app/planner.py` / `app/coder.py` call the LLM through an injected `llm: LLMFn` (default
  `app.llm.complete`); tests pass fakes, so no test hits the real API. All prompt text is in
  `app/prompts.py`. The Planner can stop early with `CANNOT_ANSWER:`.
- `app/reviewer.py` is the deterministic gate (sqlglot, BigQuery dialect, no LLM): one statement,
  read-only, only `sales` (or CTEs), no `*` except `COUNT(*)`, only selected columns or query aliases.
- `app/chain.py` turns expected errors into a `ChainResult.status` + message (keeping partial
  results); unexpected exceptions propagate. The UI renders by status and holds no logic.
- The openai SDK (3.x) uses `httpx2`, not `httpx`. UI tests use `streamlit.testing.v1.AppTest`
  and patch `app.chain.run` / `app.config.load_settings`.

## Commands

Run from the project root in PowerShell:

```powershell
.venv\Scripts\Activate.ps1                    # activate the venv
pip install -r requirements-dev.txt           # install runtime + dev deps
ruff check .                                  # lint
ruff format .                                 # auto-format (plan/ is excluded)
pytest                                        # all tests (LLM is faked; no API key needed)
pytest tests/test_schema.py::test_name        # a single test
streamlit run streamlit_app.py                # run the UI
python -m app.llm                             # one real LLM smoke call (costs a request)
uvicorn --factory gateway.main:create_app --port 8081 --no-access-log   # run the gateway
pytest tests/gateway                          # gateway tests only
```

Quality gate (CI runs exactly this; all must pass):

```powershell
ruff check .; ruff format --check .; pytest --cov   # coverage of app/ + gateway/ (combined) must be >= 90%
```

Docker (requires Docker Desktop running):

```powershell
docker build -t sql-planner:local .
docker run --rm -p 8080:8080 -v "${PWD}/.env:/app/.env:ro" sql-planner:local   # http://localhost:8080
```

`.env` values are quoted, so don't use `docker run --env-file .env` (it keeps the quotes in the
values); mount it read-only instead and let python-dotenv parse it. The image contains no secrets.

`tests/conftest.py` fails any test that builds the real OpenAI client: pass a fake `llm=`
(Planner/Coder/chain) or `client=` (`app.llm.complete`) instead.

## Git workflow and CI

- Never commit directly to `main`: work on a branch, open a PR (`gh pr create`), wait for CI, and
  merge only after the user approves.
- Repo: `jansidv99-lab/sql_planner_cicd_gcp_api_gateway` (public; copied from the original
  `jansidv99-lab/sql_planner_cicd_gcp`). `.github/workflows/ci.yml` runs on PRs and
  pushes to `main`: job `quality` (the gate above) then job `docker` (build image + container
  smoke test on `/_stcore/health`). CI needs no secrets. The `docker` job builds only the
  planner image; the gateway gets its own image and deploy in G4.
- `git push` authenticates via Git Credential Manager; the `gh` token has no `workflow` scope.
- Branch protection isn't configured, so "CI green before merge" is a convention, not enforced
  by GitHub. (The original repo was private on a free plan, where it isn't available; this
  repo is public, so it could be enabled.)

## CD (Cloud Run)

- `.github/workflows/cd.yml` runs after CI succeeds on `main` (`workflow_run`) or manually
  (`workflow_dispatch`): keyless auth (WIF) → build → push to Artifact Registry (tag = commit SHA)
  → `gcloud run deploy sql-planner-apigw` (region `asia-south1`) → health check. `workflow_run`
  only uses the workflow file from `main`, so CD changes can't be tested on a PR.
- One-time setup is `scripts/gcp_setup.sh` (re-runnable; needs `.env` and an owner gcloud login).
  Every name comes from `APP="sql-planner-apigw"`: Cloud Run service, Artifact Registry repo,
  secret `sql-planner-apigw-openai-api-key`, SAs `sql-planner-apigw-runtime` /
  `sql-planner-apigw-deployer`, WIF provider `github-sql-planner-apigw` (only this repo's
  `main`, in the shared pool `github-pool`). Config lives in GitHub repo variables.
- The setup script creates the service with a placeholder image so the deployer's
  `run.developer` can be granted **on this service only** (not project-wide).
- The same GCP project hosts other apps: never modify their resources. That includes the
  original app (`sql-planner` service/repo/secret, `sql-planner-runtime`, `sql-planner-deployer`,
  provider `github-sql-planner`), everything `sql-planner-pm*`, `gh-deployer`, `run-runtime`,
  `github-provider`, repo `apps`, secret `openai-api-key`, and the `driver-*` and
  `data-analysis-script-generator` services.
- The service must be public (`allUsers` → `roles/run.invoker`, set once by the owner after the
  setup script). The deployer can't change access. CD's smoke check relies on public access: on
  a private service it gets 403.
- Rollback: `gcloud run services update-traffic sql-planner-apigw --region asia-south1
  --to-revisions <previous-revision>=100`, or re-run CD from the Actions tab.
- Claude Code's auto mode blocks some steps; hand them to the user (`! <command>` in the
  prompt or the GitHub UI): writing to Secret Manager (so `gcp_setup.sh` on a fresh setup),
  granting `allUsers` access, and merging PRs to `main` (it triggers a production deploy).
  Read-only `gcloud` checks and the non-secret steps of the setup script are allowed.

## LLM gateway (`gateway/`, phases G0–G15)

- Separate deployable from `app/` (no imports between them). Contract and design: `docs/gateway/`
  (OpenAI-compatible API, field allowlist, error table, threat model); status table:
  `plan/v2_api_gateway/00_master_plan.md`. Not deployed until G4.
- `gateway/main.py: create_app(settings)` is a factory (no side effects at import): settings from
  `GATEWAY_*` env vars (`gateway/config.py`, all problems reported at once, startup fails fast),
  lifespan opens one shared `httpx2.AsyncClient` on `app.state.http`.
- Every error is OpenAI-shaped (`gateway/errors.py`): raise a `GatewayError` subclass. Unexpected
  exceptions are turned into 500s by `RequestIdMiddleware` (not an `Exception` handler, which
  Starlette runs outside our middleware and would drop `X-Request-ID`).
- `RequestIdMiddleware` (pure ASGI, stream-safe) sets `request_id_var`; every `gateway` log line
  carries it, plus one `request` access line (path only, never the query string or bodies).
- Runtime deps are in `requirements-gateway.txt` (the planner image doesn't get them); use
  `httpx2` (already used by the openai SDK and Starlette's `TestClient`), not `httpx`.
- Tests: `tests/gateway/conftest.py` blocks real upstream connections (use `httpx2.MockTransport`)
  and captures logs via the `logs` fixture; build apps with the `app`/`client` fixtures.

## Logging and tracing (Phase 12)

- `app/observability.py`: `setup_logging()` attaches google-cloud-logging's `StructuredLogHandler`
  (JSON on stdout → Cloud Logging, auto-linked to the active trace; needs no credentials) to the
  `app` logger; `setup_tracing()` installs OpenTelemetry → Cloud Trace (every run sampled) only on
  Cloud Run (`K_SERVICE`) or with `TRACING_ENABLED=true`. The OTel resource's `service.name` is
  `K_SERVICE` (fallback `sql-planner`), but the Cloud Trace exporter doesn't store it on spans:
  find an app's traces through its own `chain finished` log lines (see below). Both are called once from
  `streamlit_app.py` via `st.cache_resource`.
- Each chain run = trace `chain.run` → `planner`/`coder` (→ `llm.complete`) / `reviewer`, plus one
  log line `chain finished` (status, error type, columns, durations). Use `observability.span()`,
  which records only the error **type**: never put request text, prompts, outline or SQL in logs
  or span attributes (`tests/test_observability.py` checks this).
- Tests: `tests/conftest.py` installs an in-memory span exporter (`spans` fixture) and resets the
  `app` logger after each test.
- Log lines must be written while the relevant span is active, or they lose the trace link.
- To inspect production: `gcloud logging read 'resource.labels.service_name="sql-planner-apigw" AND
  jsonPayload.message="chain finished"'`, then fetch the trace by ID
  (`GET cloudtrace.googleapis.com/v1/projects/<project>/traces/<id>`); the v1 list endpoint
  returned nothing during verification.

## Goal

Implement a "SQL script generator" as a prompt chain in Python:

1. **Planner:** generates the outline, a high-level plan.
2. **Coder:** generates the SQL code based on the outline.
3. **Reviewer (gate check):** deterministic check of the generated SQL (parses, plus the safety rules in
   Architecture), no retries.
4. **UI:** a Streamlit app where the user enters input and sees the output.
5. **CI/CD pipeline:** production-ready app with full CI and CD, deploying to GCP.
6. **Schema:** a fixed `sales` table with 4 columns: `order_date`, `quantity`, `product`, `amount`. The user may only select
   from these columns, and the schema is injected into the Planner and Coder prompts to prevent the
   LLM from hallucinating tables/columns.

## Decisions

- SQL dialect: BigQuery (used by the Coder prompt and the `sqlglot` parse check).
- CI/CD: GitHub Actions; hosting: Cloud Run.
- Code generation only: the app never executes SQL or touches data.

## Environment

Copy `.env.example` to `.env` and fill it in (`.env` holds secrets and is gitignored). It defines:
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MODEL` — LLM access via an OpenAI-compatible endpoint; read the model name from `MODEL`, don't hardcode it.
- `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER` — deployment target.
- `GATEWAY_PROVIDER_BASE_URL`, `GATEWAY_PROVIDER_API_KEY`, `GATEWAY_DEFAULT_MODEL` (required) and
  `GATEWAY_LOG_LEVEL` (default `INFO`) — gateway settings. The base URL must use `https://`;
  `http://` is allowed only for `localhost` or `127.0.0.1` (a local fake provider). `.env` never
  overrides variables already set in the environment.

## Workflow rules

1. **Plan first:** for every step, write a detailed plan doc in `/plan` with clear descriptions of each topic.
2. **Review:** ask the user to review the plan doc.
3. **Permission:** always ask for permission before making any change to code.
4. **Phased implementation:** plan code phase by phase, step by step, stating the purpose of each step and its dependencies.
5. **Commit step:** always ask for permission before every commit
