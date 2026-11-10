# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Phases 0–8 are done (app runs locally, quality gate in place); Docker, CI, CD and
logging/tracing are next
(see `plan/00_master_plan.md`). Python 3.11, with dependencies pinned in `requirements*.txt`.

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
```

Quality gate (CI runs exactly this; all must pass):

```powershell
ruff check .; ruff format --check .; pytest --cov   # coverage of app/ must be >= 90%
```

`tests/conftest.py` fails any test that builds the real OpenAI client: pass a fake `llm=`
(Planner/Coder/chain) or `client=` (`app.llm.complete`) instead.

## Goal

Implement a "SQL script generator" as a prompt chain in Python:

1. **Planner:** generates the outline, a high-level plan.
2. **Coder:** generates the SQL code based on the outline.
3. **Reviewer (gate check):** checks that the generated SQL parses , no retries.
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

`.env` (contains secrets — never commit; add to `.gitignore` when the repo is initialized) defines:
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MODEL` — LLM access via an OpenAI-compatible endpoint; read the model name from `MODEL`, don't hardcode it.
- `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER` — deployment target.

## Workflow rules

1. **Plan first:** for every step, write a detailed plan doc in `/plan` with clear descriptions of each topic.
2. **Review:** ask the user to review the plan doc.
3. **Permission:** always ask for permission before making any change to code.
4. **Phased implementation:** plan code phase by phase, step by step, stating the purpose of each step and its dependencies.
