# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

New project: no code, dependencies, or tooling exist yet. When build/test/lint/run commands
and the module layout are created, add them to this file.

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
