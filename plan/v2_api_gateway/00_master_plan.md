# LLM API Gateway: Master Plan (v2)

**Status:** APPROVED (2026-11-11). Prerequisite done: dedicated GCP resources for this repo
([01_dedicated_gcp_resources.md](01_dedicated_gcp_resources.md)). G0 design docs written
(`docs/gateway/`); G1 skeleton implemented; next: Phase G2 plan doc.

| Phase | Plan doc | Result |
|---|---|---|
| Pre: dedicated GCP resources | `01_dedicated_gcp_resources.md` | ✅ |
| G0 Concepts and design | `02_phaseG0_concepts_design.md` | ✅ `docs/gateway/` |
| G1 Gateway skeleton | `03_phaseG1_skeleton.md` | ✅ 39 gateway tests, coverage 100 % |
| G2 Pass-through proxy | `04_phaseG2_passthrough.md` | ⏳ next |
| G3 Client authN/authZ | `05_phaseG3_auth.md` | |
| G4 Deploy the gateway | `06_phaseG4_deploy.md` | |
| G5 Planner as first client | `07_phaseG5_planner_client.md` | |
| G6 Routing and aliases | `08_phaseG6_routing.md` | |
| G7 Resilience | `09_phaseG7_resilience.md` | |
| G8 Rate limits and budgets | `10_phaseG8_limits.md` | |
| G9 Metering and cost | `11_phaseG9_metering.md` | |
| G10 Streaming | `12_phaseG10_streaming.md` | |
| G11 Caching | `13_phaseG11_caching.md` | |
| G12 Guardrails | `14_phaseG12_guardrails.md` | |
| G13 Observability and SLOs | `15_phaseG13_observability.md` | |
| G14 Security and prod readiness | `16_phaseG14_production.md` | |
| G15 Retrospective | `17_phaseG15_retrospective.md` | |

## Context

The SQL planner (`app/`) calls the model provider directly: `app/llm.py:complete()` builds an
`openai.OpenAI` client from `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `MODEL` (`app/config.py`), so
every app that wants an LLM needs its own provider key, retries, limits, cost tracking and
logging. The goal is an **LLM API gateway**: one service that sits between all applications and
the model providers, so that:

- apps never hold provider keys (only the gateway does, in Secret Manager);
- auth, routing, retries/failover, rate limits, token budgets, caching, cost and observability
  are implemented **once**, centrally;
- providers/models can be swapped without changing apps.

This is a **learning project that ends at production level**: each phase introduces one gateway
concept, ships it as a tested, deployed increment, and records what was learned.

**Decisions (from the user):** build our own gateway (Python, FastAPI); one provider for now
(the current OpenAI-compatible endpoint), with a provider abstraction ready for more; code in
this repo under `gateway/`, deployed as its own Cloud Run service; state is free-tier first
(in-memory to learn the algorithms → Firestore for shared state; Redis described, not deployed).

**Process (CLAUDE.md rules):** on approval, this master plan is saved as
`plan/v2_api_gateway/00_master_plan.md`. Each phase then gets its own detailed plan doc
(`plan/v2_api_gateway/NN_phaseX_<name>.md`), reviewed by the user before any code, then one
branch + PR per phase, CI green, merge with user approval.

---

## Target architecture

```
 Streamlit SQL planner (app/)      other apps / curl / notebooks
            │  OpenAI SDK, base_url = gateway, key = gateway client key
            ▼
 ┌──────────────────────── LLM Gateway (gateway/, Cloud Run) ────────────────────────┐
 │ request ID ─► authN (client key) ─► authZ (allowed models) ─► guardrails          │
 │   ─► rate limit + token budget ─► cache lookup ─► router (alias → provider/model)  │
 │   ─► resilience (timeout, retry, circuit breaker, fallback) ─► provider adapter    │
 │   ◄─ metering (tokens, cost) ◄─ response / SSE stream ◄────────────────────────────┤
 │ cross-cutting: structured logs (no prompt text), OTel traces + metrics            │
 └───────────────┬───────────────────────────────┬──────────────────────────────────┘
                 ▼                               ▼
   OpenAI-compatible provider          Firestore (limits, budgets, cache, usage)
   (key from Secret Manager)           Secret Manager (provider key, client keys)
```

**API contract:** the gateway exposes the **OpenAI Chat Completions API**
(`POST /v1/chat/completions`, `GET /v1/models`) so any OpenAI SDK client works by changing only
`base_url` and the key. Clients ask for a **logical model alias** (e.g. `sql-planner-default`);
the gateway maps it to a real provider + model.

**Proposed layout (detailed in Phase G1):**
```
gateway/
  main.py            # FastAPI app factory, middleware order, routes
  config.py          # settings (env + routing YAML), validated at startup
  api/               # routes: chat, models, health, admin
  auth.py            # client keys → ClientIdentity
  router.py          # alias → [provider/model candidates]
  providers/         # Provider protocol; openai_compat.py; fake.py (tests/demos)
  resilience.py      # timeouts, retry+backoff+jitter, circuit breaker, fallback
  limits.py          # token bucket + daily token budgets (memory / Firestore backends)
  cache.py           # exact-match response cache
  metering.py        # usage records, price table, cost
  observability.py   # reuse the app's logging/tracing approach
  errors.py          # OpenAI-shaped error responses
tests/gateway/       # unit + API tests (httpx/FastAPI TestClient, fake provider)
gateway.Dockerfile, gateway/routes.yaml
```

---

## Phases

Each phase lists: **learn** (concepts), **build**, **done when** (verifiable). Every phase keeps
the quality gate green (`ruff check`, `ruff format --check`, `pytest --cov`, coverage ≥ 90 % for
`app/` and `gateway/`) and never logs prompt/response text.

### Stage A: Foundations

**G0. Concepts and design (docs only)**
- Learn: what an API gateway is (single entry point, cross-cutting concerns, north-south
  traffic), why LLM gateways differ (token-based cost/limits, streaming, long latencies,
  provider outages), build vs buy (LiteLLM, Envoy AI Gateway, Apigee, Kong AI).
- Build: architecture doc + ADR "build our own, OpenAI-compatible contract", request
  lifecycle diagram, error model, non-goals, threat model (key leakage, abuse, cost blowout).
- Done when: user has reviewed the ADR and the API contract.

**G1. Gateway skeleton**
- Learn: ASGI, FastAPI app factory, dependency injection, middleware order, async I/O, settings
  validation, health vs readiness probes.
- Build: `gateway/` package; `GET /healthz`, `GET /readyz`; settings loader (same style as
  `app/config.py`: frozen dataclass, key kept out of `repr`); request-ID middleware; JSON
  structured logging (reuse the `StructuredLogHandler` pattern from `app/observability.py`);
  pinned deps (`fastapi`, `uvicorn`, `httpx` for upstream + tests; note the openai SDK itself
  uses `httpx2`); ruff/pytest/coverage config extended to `gateway/`.
- Done when: `uvicorn gateway.main:app` serves health locally; tests run with no network.

**G2. Pass-through proxy (OpenAI-compatible)**
- Learn: reverse proxying, connection pooling, timeouts (connect/read/total), mapping upstream
  errors to a stable error format, hiding upstream credentials, hop-by-hop headers.
- Build: `POST /v1/chat/completions` forwarding to the provider via a shared async
  `httpx.AsyncClient`; `GET /v1/models`; OpenAI-shaped errors (`errors.py`); upstream key read
  from env (Secret Manager on Cloud Run); `Provider` protocol + `openai_compat` adapter +
  `fake` adapter (scriptable latency/errors/429s for tests and demos, never routed in prod).
- Done when: the real OpenAI SDK pointed at the local gateway gets a completion; tests cover
  success, upstream 4xx/5xx/timeout mapping, using the fake provider.

### Stage B: First production slice

**G3. Client authentication and authorization**
- Learn: API keys vs OAuth/JWT vs cloud IAM; storing only key **hashes**; constant-time
  comparison; per-client permissions; key rotation.
- Build: `Authorization: Bearer <client-key>` → `ClientIdentity` (id, allowed aliases,
  limits); keys stored as SHA-256 hashes (in a Secret Manager secret holding the client
  registry JSON); 401/403 in OpenAI error shape; `scripts/` helper to mint a key (prints once).
- Done when: unknown/revoked keys get 401, disallowed models 403; key value never logged.

**G4. Containerize and deploy the gateway (second Cloud Run service)**
- Learn: multi-service monorepo CI/CD, least-privilege per service, secrets per service.
- Build: `gateway.Dockerfile` (same hardening as `Dockerfile`: slim, non-root, `exec`);
  CI `docker` job builds + smoke-tests both images (`/healthz`); `cd.yml` deploys both
  services; `scripts/gcp_setup.sh` extended with gateway resources from one prefix
  (service, runtime/deployer bindings; deployer `run.developer` on the service only, the
  pattern already used for `sql-planner-apigw`); the provider-key secret is granted to the
  **gateway** runtime SA.
- Done when: CD deploys the gateway, smoke check green, curl with a client key works.

**G5. SQL planner becomes the gateway's first client**
- Learn: migrating a client behind a gateway with zero app-logic change; blast radius.
- Build: planner's `OPENAI_BASE_URL` → gateway URL, `OPENAI_API_KEY` → its gateway client key
  (new secret), `MODEL` → alias `sql-planner-default`. No change to `app/llm.py` logic
  expected. Remove the provider key from the planner's runtime SA (the security win).
- Done when: the live planner works end to end through the gateway; the planner SA can no
  longer read the provider secret.

### Stage C: Gateway features

**G6. Routing and model aliases**
- Learn: logical vs physical models, config-driven routing, hot reload trade-offs.
- Build: `gateway/routes.yaml`: alias → ordered candidates `{provider, model, params caps}`;
  per-client alias allowlist; `GET /v1/models` lists the client's aliases; adapter registry
  so adding a provider later (e.g. Vertex Gemini, Anthropic) is one new adapter + config.
- Done when: aliases resolve per config; unknown alias → 404 in OpenAI shape.

**G7. Resilience: retries, circuit breaker, fallback**
- Learn: retryable vs non-retryable errors, exponential backoff with jitter, retry budgets,
  circuit breaker states (closed/open/half-open), fallback chains, deadlines.
- Build: `resilience.py`; per-candidate timeout; retry only on connect errors/429/5xx with
  `Retry-After` respected; circuit breaker per upstream; fallback to the next candidate in the
  alias (with one provider: e.g. a second model); overall request deadline.
- Done when: chaos tests with the fake provider prove retry, breaker open/close and fallback;
  response header shows which candidate served.

**G8. Rate limiting and token budgets**
- Learn: token bucket vs fixed/sliding window, request limits vs **token** limits, estimating
  tokens before the call and reconciling after, distributed counters and their limits.
- Build: `limits.py` with a backend interface: in-memory first (learn the algorithm, tests),
  then Firestore (transactions; note the ~1 write/s per document guideline and why sharded
  counters / Redis exist at scale). Per-client RPM + daily token budget; 429 with
  `Retry-After` and `x-ratelimit-*` headers.
- Done when: limits hold across 2 Cloud Run instances (Firestore backend); tests cover refill,
  burst, budget exhaustion and reset.

**G9. Usage metering and cost**
- Learn: tokens → cost, price tables, chargeback per client, log-based metrics.
- Build: `metering.py`: one usage record per request (client, alias, provider model,
  prompt/completion tokens, latency, cost, cache hit, status; never text) written as a
  structured log line + Firestore daily aggregates; `GET /admin/usage` (admin key);
  Cloud Logging log sink to BigQuery (free tier) for ad-hoc reports; budget alert.
- Done when: usage for the planner's requests matches the provider's reported tokens.

**G10. Streaming (Server-Sent Events)**
- Learn: SSE framing, backpressure, client disconnects, metering a stream
  (`stream_options.include_usage`), Cloud Run streaming/timeouts.
- Build: `stream: true` support end to end, errors mid-stream, usage recorded at stream end,
  rate-limit/budget checks before the first byte.
- Done when: OpenAI SDK streaming through the gateway works locally and on Cloud Run.

**G11. Response caching**
- Learn: cache keys (normalized request hash), what is safe to cache (deterministic requests,
  `temperature=0`), TTLs, per-client isolation, semantic caching (discussed only).
- Build: exact-match cache (Firestore, TTL policy) keyed by client + alias + normalized
  messages/params; `Cache-Control: no-cache` opt-out; `x-cache: HIT|MISS`; hits metered as
  zero provider cost.
- Done when: repeated planner request is served from cache; hit rate visible in metrics.

### Stage D: Production hardening

**G12. Guardrails and data protection**
- Learn: input validation, payload limits, `max_tokens` caps, model allowlists, PII handling,
  data-retention policy, what belongs in the gateway vs the app (prompt-injection defense
  stays app-side, e.g. the planner's Reviewer).
- Build: request size / message count limits, per-alias `max_tokens` cap, optional regex PII
  redaction hook (off by default), test asserting no prompt text in logs/spans (extend the
  existing check in `tests/test_observability.py`).

**G13. Observability across services and SLOs**
- Learn: W3C `traceparent` propagation, RED metrics, OTel metrics → Cloud Monitoring,
  SLIs/SLOs, error budgets, alerting.
- Build: one trace spanning planner → gateway → provider call; metrics: request rate, error
  rate, latency p50/p95/p99, tokens, cost, cache hit rate, breaker state; dashboard; SLO
  (e.g. 99 % non-5xx, p95 < X s excluding provider time) with alert policies.
- Done when: a single planner request shows as one trace across both services.

**G14. Security and production readiness**
- Learn: defense in depth, service-to-service IAM, secret rotation, supply-chain security,
  capacity planning, safe rollouts.
- Build: gateway **not public**: `run.invoker` only for client SAs (planner sends a Google ID
  token in addition to its client key); client-key rotation runbook; `pip-audit` in CI and
  Artifact Registry vulnerability scanning; load test (locust) to choose concurrency, min/max
  instances and timeouts; canary deploys with tagged revisions + traffic split; runbook
  (provider outage, budget exhausted, key leak) and rollback for both services.
- Done when: load test meets the SLO; the public internet gets 403 from the gateway; runbook
  reviewed.

**G15. Retrospective and next steps**
- Compare our gateway with LiteLLM / Envoy AI Gateway / Apigee on the same feature list;
  document when to build vs buy; optional extension: add a second real provider (Vertex AI
  Gemini via service account, no API key) to exercise cross-provider failover and request
  translation.

### Phase dependencies

G0 → G1 → G2 → G3 → G4 → G5 (first production slice) → G6 → G7 → G8 → G9 → G10 → G11 →
G12 → G13 → G14 → G15. G10 and G11 can swap; G12 can start after G6.

---

## Owner actions expected (auto mode blocks these for Claude)

Enabling Firestore (Native mode) + creating the database (G8), writing secrets (G3/G4/G5),
granting `run.invoker` (G14), and merging PRs to `main` (every phase). Each phase doc lists
the exact commands.

## Verification (per phase and overall)

- Quality gate on every PR (CI runs it): `ruff check .; ruff format --check .; pytest --cov`.
- Gateway tests never hit the network: fake provider + `httpx` mocking; a conftest guard like
  the existing one in `tests/conftest.py` fails any test that would call the real provider.
- After each deploying phase: CD green, `/healthz` ok, a scripted smoke request with a client
  key, and (from G5) the live planner works through the gateway; read-only `gcloud` checks of
  IAM and logs (`chain finished` + gateway usage lines), traces fetched by ID.
- Final acceptance (G14): load test report, SLO dashboard, runbook drill (simulate provider
  outage with the breaker), gateway unreachable from the public internet.

## Critical files

- New: `gateway/**`, `tests/gateway/**`, `gateway.Dockerfile`, `gateway/routes.yaml`,
  `plan/v2_api_gateway/00_master_plan.md` + per-phase docs.
- Modified: `pyproject.toml` (coverage source, ruff), `requirements*.txt`,
  `.github/workflows/ci.yml`, `.github/workflows/cd.yml`, `scripts/gcp_setup.sh`,
  `CLAUDE.md`, and (G5 config only, G13 trace headers) the planner's deployment settings.
- Reused: `app/config.py` settings pattern, `app/observability.py` logging/span helpers and
  privacy rule, `app/llm.py` error-mapping ideas, `tests/conftest.py` network guard pattern,
  the service-level deployer pattern in `scripts/gcp_setup.sh`.
