# SQL Script Generator — Master Plan

**Status:** DRAFT, waiting for review. No code will be written until this plan is approved and permission is given for each phase.

---

## 1. What we are building

A Python app that turns a plain-English request into a validated SQL query against one fixed sales table. It works as a **prompt chain**:

```
User (Streamlit UI)
   │  picks columns + types a request
   ▼
[1] Planner  ── LLM ──►  outline: the steps the query needs (filter, group, sort…)
   │
   ▼
[2] Coder    ── LLM ──►  SQL written from the outline
   │
   ▼
[3] Reviewer (gate, no LLM) ──► parses the SQL and checks it against the schema
   │            │
   │ pass       │ fail → show the Reviewer's errors to the user (no retries)
   ▼
UI shows: the outline, the SQL and the review result
```

## 2. Schema (fixed, the only source of truth)

Table: `sales`

| Column       | Type            | Meaning                         |
|--------------|-----------------|---------------------------------|
| `order_date` | `DATE`          | Date the order was placed       |
| `quantity`   | `INTEGER`       | Number of units ordered         |
| `product`    | `VARCHAR`       | Product name                    |
| `amount`     | `DECIMAL(10,2)` | Order value (currency)          |

**How this prevents hallucination:**
1. The user can only **select** columns from this list in the UI. They can't type column names.
2. Only the selected columns (with their types) go into the Planner and Coder prompts.
3. The Reviewer **rejects** SQL that refers to any table other than `sales`, or to any column the user didn't select.

## 3. Proposed project layout

```
sql_planner_cicd_gcp/
├── app/
│   ├── __init__.py
│   ├── config.py        # loads .env settings
│   ├── schema.py        # the sales schema (one definition, used everywhere)
│   ├── llm.py           # thin wrapper around the OpenAI-compatible client
│   ├── prompts.py       # prompt templates for the Planner and Coder
│   ├── planner.py       # step 1
│   ├── coder.py         # step 2
│   ├── reviewer.py      # step 3 (gate)
│   └── chain.py         # runs 1 → 2 → 3 with retries
├── streamlit_app.py     # UI entry point
├── tests/               # pytest; the LLM is mocked so tests need no API key
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── .gitignore
├── .github/workflows/
│   ├── ci.yml
│   └── cd.yml
└── plan/                # this folder: one plan doc per phase
```

---

## 4. Phases

Each phase lists its **purpose**, **steps**, **depends on** and **done when**. Before starting a phase I'll write a detailed plan doc for it (`plan/0N_<phase>.md`) and ask for your review and permission.

### Phase 0 — Project setup
- **Purpose:** a clean, reproducible base, with secrets protected from the start.
- **Steps:**
  1. `git init`; add a `.gitignore` that excludes `.env`, `.venv/`, `__pycache__/`.
  2. Create a virtual environment.
  3. `requirements.txt`: `openai`, `streamlit`, `sqlglot`, `python-dotenv`.
     `requirements-dev.txt`: `pytest`, `ruff`.
  4. Create the folder layout from section 3 with empty modules.
  5. Add `.env.example` with variable names only (no values).
- **Depends on:** nothing.
- **Done when:** `pip install -r requirements-dev.txt` works and `git status` doesn't show `.env`.

### Phase 1 — Config and schema
- **Purpose:** one place for settings and one definition of the schema.
- **Steps:**
  1. `config.py`: read `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MODEL` from the environment, and fail clearly if any is missing.
  2. `schema.py`: define the `sales` table and its 4 columns and types.
  3. Helper `schema_for_prompt(selected_columns)` → text block describing only the selected columns.
  4. Helper `validate_selection(columns)` → rejects anything that isn't one of the 4 columns.
- **Depends on:** Phase 0.
- **Done when:** unit tests for both helpers pass.

### Phase 2 — LLM client
- **Purpose:** a single, mockable point of contact with the LLM.
- **Steps:**
  1. `llm.py`: function `complete(system, user) -> str` using `openai.OpenAI(base_url=..., api_key=...)` and the model from `MODEL`.
  2. Low temperature (e.g. 0) so results are repeatable; a timeout; clear error messages.
- **Depends on:** Phase 1 (config).
- **Done when:** a manual smoke call returns text; tests can replace `complete` with a fake.

### Phase 3 — Planner (chain step 1)
- **Purpose:** turn the user request into a short, structured outline before any SQL is written.
- **Steps:**
  1. Planner prompt in `prompts.py`: includes the schema block and the user request; asks for a numbered outline (columns used, filters, aggregations, grouping, ordering, limit).
  2. `planner.py`: `make_plan(request, selected_columns) -> str`.
- **Depends on:** Phases 1, 2.
- **Done when:** tests with a mocked LLM check that the prompt contains only the selected columns.

### Phase 4 — Coder (chain step 2)
- **Purpose:** write SQL that follows the outline.
- **Steps:**
  1. Coder prompt: schema block + outline; asks for **one `SELECT` statement only** in BigQuery SQL, SQL only, no explanation.
  2. `coder.py`: `write_sql(plan, selected_columns) -> str`; removes markdown code fences from the answer.
- **Depends on:** Phases 1, 2, 3.
- **Done when:** tests check fence removal and that the prompt contains only the selected columns.

### Phase 5 — Reviewer (chain step 3, gate check)
- **Purpose:** never show SQL that doesn't parse or that goes outside the schema. This step doesn't use an LLM, so its result is the same every time.
- **Steps (all in `reviewer.py`, using `sqlglot`):**
  1. **Parses:** `sqlglot.parse` with `dialect="bigquery"`; a parse error means fail.
  2. **Single statement:** exactly one statement.
  3. **Read-only:** must be a `SELECT`; anything else (`INSERT`, `UPDATE`, `DELETE`, `DROP`, …) fails.
  4. **Table check:** only `sales` is referenced.
  5. **Column check:** every column referenced is in the user's selection (aliases defined in the query are allowed).
  6. Returns `ReviewResult(passed: bool, errors: list[str])`.
- **Depends on:** Phase 1 (schema).
- **Done when:** tests cover a valid query, a syntax error, a `DROP`, an unknown table, an unselected column and multiple statements.

### Phase 6 — Chain orchestrator
- **Purpose:** connect the steps into one call.
- **Steps:**
  1. `chain.py`: `run(request, selected_columns)`.
  2. Flow: validate selection → plan → code → review, each step run **once** (no retries).
  3. Return a result object: outline, SQL, review result (passed + errors).
- **Depends on:** Phases 3, 4, 5.
- **Done when:** tests with a mocked LLM cover a passing run and a failing run (errors returned, SQL not marked valid).

### Phase 7 — Streamlit UI
- **Purpose:** the user-facing app.
- **Steps:**
  1. `streamlit_app.py`: show the schema table; `st.multiselect` limited to the 4 columns; a text box for the request; a "Generate" button.
  2. Show the outline, the SQL (`st.code(..., language="sql")`) and a clear ✅ pass / ❌ fail badge with the Reviewer's errors.
  3. Spinner while running; friendly message if the LLM call fails.
- **Depends on:** Phase 6.
- **Done when:** `streamlit run streamlit_app.py` works locally from start to finish.

### Phase 8 — Tests and code quality
- **Purpose:** a safety net that CI will run.
- **Steps:**
  1. Finish the pytest suite (built up during Phases 1–6); the LLM is always mocked.
  2. `ruff` lint/format settings in `pyproject.toml`.
- **Depends on:** Phases 1–7.
- **Done when:** `ruff check .` and `pytest` both pass locally with no API key set.

### Phase 9 — Containerize
- **Purpose:** the same build runs locally, in CI and on GCP.
- **Steps:**
  1. `Dockerfile`: `python:3.11-slim` (matches local Python 3.11.9), install requirements, run Streamlit on `$PORT` (Cloud Run supplies this) at address `0.0.0.0`.
  2. `.dockerignore` (excludes `.env`, `.venv`, `tests`, `plan`).
- **Depends on:** Phase 7.
- **Done when:** `docker build` and `docker run` serve the app locally.

### Phase 10 — CI pipeline
- **Purpose:** every push and pull request is checked automatically.
- **Steps (`.github/workflows/ci.yml`):** checkout → set up Python → install dev requirements → `ruff check` → `pytest` → `docker build` (to prove the image builds).
- **Depends on:** Phases 8, 9; a GitHub repository.
- **Done when:** CI is green on a pull request.

### Phase 11 — CD pipeline to GCP
- **Purpose:** every merge to `main` deploys automatically to production.
- **Steps:**
  1. **One-time GCP setup** (documented as commands for you to run): enable the Cloud Run, Artifact Registry and Secret Manager APIs; create an Artifact Registry repository; store `OPENAI_API_KEY` in Secret Manager; create a deploy service account; set up **Workload Identity Federation** so GitHub can deploy without a stored JSON key.
  2. `.github/workflows/cd.yml` (on push to `main`, after CI passes): authenticate to GCP → build and push the image to Artifact Registry (tagged with the commit SHA) → `gcloud run deploy` with the secret mounted as an env var and `OPENAI_BASE_URL` / `MODEL` as plain env vars.
  3. After deploying, do a smoke check against the service URL.
  4. Rollback: redeploy the previous image tag (documented).
- **Depends on:** Phase 10; a GCP project (`GCP_PROJECT_ID` in `.env`).
- **Done when:** merging to `main` updates the live Cloud Run URL.

---

## 5. Dependency summary

```
P0 ─► P1 ─► P2 ─► P3 ─► P4 ─┐
       │                    ├─► P6 ─► P7 ─► P8 ─► P9 ─► P10 ─► P11
       └──────────► P5 ─────┘
```
P5 (Reviewer) needs only the schema, so it can be built alongside P2–P4.

## 6. Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | SQL dialect for parsing and generation? | **BigQuery** (default, not yet confirmed; easy to change: one setting) |
| 2 | CI/CD platform? | **GitHub Actions** ✅ |
| 3 | GCP hosting target? | **Cloud Run** ✅ |
| 4 | Retries when the Reviewer fails? | **No retries** ✅: show the errors to the user |
| 5 | Execute the SQL on data? | **No** ✅: code generation only, no data |
