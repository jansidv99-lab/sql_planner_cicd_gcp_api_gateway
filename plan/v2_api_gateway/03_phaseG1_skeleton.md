# Phase G1 — Gateway skeleton (detailed plan)

**Status:** DONE (2026-11-11) on branch `feat/gateway-g1-skeleton`: 180 tests (39 gateway), coverage 100 %; verified with a real uvicorn run (health, readiness, 404 shape + `X-Request-ID`, fail-fast config).
**Deviation:** unexpected exceptions become 500s in `RequestIdMiddleware` instead of an `Exception` handler (Starlette runs that handler outside our middleware, so the response would lose `X-Request-ID`).
**Part of:** [00_master_plan.md](00_master_plan.md)
**Depends on:** G0 design docs ✅ (`docs/gateway/`: architecture §1 layout, API contract §4–5
headers and error model).
**Unblocks:** G2 (pass-through proxy), which adds the chat/models routes on this skeleton.

## Goal

A runnable, tested, empty gateway: a FastAPI app with health/readiness probes, settings
validated at startup, a request-ID middleware, structured JSON logs, and OpenAI-shaped errors
for every failure, so all later phases only add features. No provider calls, no deployment yet
(deployment is G4).

## What you'll learn

- **ASGI** and why FastAPI/uvicorn are async; what blocks the event loop.
- **App factory** (`create_app(settings)`) vs a module-level app: testability, no side effects
  at import.
- **Lifespan**: creating shared resources (the HTTP connection pool) once at startup and
  closing them at shutdown.
- **Middleware order** and pure-ASGI vs `BaseHTTPMiddleware`.
- **Liveness vs readiness**: "the process is alive" vs "it can serve traffic".
- **Fail-fast configuration**: an invalid config must stop the instance before it gets traffic.

---

## Key decisions

| Topic | Decision | Why |
|---|---|---|
| HTTP library | **`httpx2`** for upstream calls and tests | Already installed (the `openai` SDK and Starlette's `TestClient` use it); no second HTTP stack |
| New deps | `fastapi==0.162.4` (adds only `annotated-doc`), `uvicorn==0.54.0`, `httpx2==2.16.0` | Verified with `pip install --dry-run` against the current pins; uvicorn/httpx2 versions match what's already installed |
| Dependency file | New **`requirements-gateway.txt`**; `requirements-dev.txt` includes it | Each deployable installs only its own runtime deps (the planner image stays unchanged; the gateway image in G4 installs only this file) |
| Env var names | Prefixed `GATEWAY_…` | The planner and gateway share one local `.env`; prefixes avoid mixing them up |
| Code sharing with `app/` | **None**: the gateway has its own small `observability.py` | Two deployables shouldn't import each other; the logging setup is ~20 lines, copied deliberately |
| Running locally | `uvicorn --factory gateway.main:create_app` | Factory keeps import side-effect free |

## Files

```
gateway/
  __init__.py
  main.py            create_app(settings=None) -> FastAPI: lifespan, middleware, routes, error handlers
  config.py          GatewaySettings + load_gateway_settings(env=None)
  errors.py          GatewayError hierarchy + handlers → OpenAI-shaped JSON
  middleware.py      RequestIdMiddleware (pure ASGI) + access log line
  observability.py   setup_logging() for the "gateway" logger (StructuredLogHandler)
  api/
    __init__.py
    health.py        GET /healthz, GET /readyz
tests/gateway/
  __init__.py
  conftest.py        settings fixture, client fixture (TestClient), network guard
  test_config.py
  test_health.py
  test_errors.py
  test_middleware.py
requirements-gateway.txt
```

Modified: `requirements-dev.txt` (+ `-r requirements-gateway.txt`), `pyproject.toml`
(coverage `source = ["app", "gateway"]`), `.env.example` (gateway vars), `CLAUDE.md`
(commands + gateway section), `plan/v2_api_gateway/00_master_plan.md` (status).

---

## Steps

### 1.1 Dependencies
- **Purpose:** add the web framework and server without touching the planner image.
- `requirements-gateway.txt`: `fastapi==0.162.4`, `uvicorn==0.54.0`, `httpx2==2.16.0`,
  `python-dotenv==1.2.4`, `google-cloud-logging==3.17.0` (same pins as `requirements.txt`
  where shared, so the dev install has no conflicts).
- `requirements-dev.txt`: add `-r requirements-gateway.txt`.

### 1.2 Settings (`config.py`)
- **Purpose:** one validated settings object, loaded once.
- `GatewaySettings` (frozen dataclass, provider key hidden in `repr`, same pattern as
  `app/config.py`):
  - `provider_base_url` ← `GATEWAY_PROVIDER_BASE_URL` (required, must be `https://`, or
    `http://localhost` for local tests)
  - `provider_api_key` ← `GATEWAY_PROVIDER_API_KEY` (required)
  - `default_model` ← `GATEWAY_DEFAULT_MODEL` (required; used by G2 until G6 adds aliases)
  - `log_level` ← `GATEWAY_LOG_LEVEL` (optional, default `INFO`, must be a valid level)
- `load_gateway_settings(env=None)`: like `app.config.load_settings` (reads `.env` without
  overriding real env vars); raises `ConfigError` listing **all** problems at once.
- Provider vars are required already in G1 so startup fails fast; G2 is the first to use them.

### 1.3 Errors (`errors.py`)
- **Purpose:** every error, from day one, uses the contract's OpenAI shape
  (`docs/gateway/03_api_contract.md` §5).
- `GatewayError(status, type, code, message)` base class; G1 subclasses:
  `InvalidRequestError` (400), `NotFoundError` (404); later phases add their own.
- Handlers: `GatewayError` → its JSON; FastAPI `RequestValidationError` → 400
  `invalid_body`; unknown route → 404 `not_found`; method not allowed → 405; any other
  exception → 500 `internal_error` with a fixed message (exception **type** logged, never
  its message, which could contain data).
- Body always includes `request_id`.

### 1.4 Request-ID middleware (`middleware.py`)
- **Purpose:** correlate a client's request with gateway logs (contract §4).
- Pure ASGI middleware (works with streaming in G10, unlike `BaseHTTPMiddleware`):
  accept `X-Request-ID` if it matches `[A-Za-z0-9._-]{1,128}`, else generate a UUID4 hex;
  store it in a `contextvars.ContextVar` and on `request.state`; add it to the response.
- One **access log line** per request after the response: method, path (no query string),
  status, duration_ms, request_id. uvicorn's own access log is turned off to avoid duplicates.

### 1.5 Logging (`observability.py`)
- **Purpose:** JSON logs that Cloud Logging parses (same approach as `app/observability.py`).
- `setup_logging(level)`: attach one `StructuredLogHandler` to the `gateway` logger
  (idempotent); a logging filter adds `request_id` from the context var to every record.
- Privacy rule (from v1): never log request bodies, prompts, responses, keys or query strings.
- Tracing (OTel) is **not** in G1; it arrives in G13 together with cross-service propagation.

### 1.6 Health routes (`api/health.py`)
- **Purpose:** probes for Cloud Run (used from G4).
- `GET /healthz` → `200 {"status": "ok"}`: always, if the process answers.
- `GET /readyz` → `200 {"status": "ready"}` when settings are loaded and the shared HTTP
  client exists (set in lifespan), else `503` (OpenAI-shaped error).

### 1.7 App factory (`main.py`)
- **Purpose:** wire everything; no side effects at import.
- `create_app(settings: GatewaySettings | None = None)`: loads settings if not given
  (fails → `ConfigError`, the process exits, startup probe fails: fail fast); lifespan
  creates one `httpx2.AsyncClient` (timeouts set in G2) on `app.state.http` and closes it at
  shutdown; registers middleware, error handlers and routers. OpenAPI docs (`/docs`) are
  disabled by default (not part of the contract; avoids exposing the surface publicly).

### 1.8 Tests (`tests/gateway/`)
- **Purpose:** prove the skeleton without network or real keys.
- `conftest.py`: `settings` fixture (fake values, `http://localhost` provider), `client`
  fixture = `TestClient(create_app(settings))` used as a context manager (runs lifespan);
  **network guard**: patch `httpx2.AsyncHTTPTransport.handle_async_request` to fail the test,
  so no gateway test can reach a real provider (G2 tests use `httpx2.MockTransport`).
- Tests:
  - config: valid, each missing var, all missing listed together, bad URL scheme, bad log
    level, key not in `repr`;
  - health: `/healthz` 200; `/readyz` 200 inside lifespan, 503 when the client isn't ready;
  - errors: unknown route 404 shape; 405; validation 400; unhandled exception → 500 with
    fixed message and no exception text in the body or logs;
  - middleware: generated ID returned; valid incoming ID echoed; invalid ID replaced;
    access log line has the fields and no query string; logs carry `request_id`.
- The existing `tests/conftest.py` fixtures (span exporter, `app` logger reset) don't affect
  gateway tests; a similar reset is added for the `gateway` logger.

### 1.9 Docs and quality gate
- `.env.example`: add the four `GATEWAY_…` vars (empty).
- `CLAUDE.md`: gateway commands (`uvicorn --factory gateway.main:create_app --port 8081`,
  `pytest tests/gateway`) and a short gateway architecture note.
- Gate: `ruff check .; ruff format --check .; pytest --cov` with coverage over `app/` +
  `gateway/` ≥ 90 % (target 100 %). CI needs no change: it already runs the gate over the
  whole repo and installs `requirements-dev.txt`.

### 1.10 PR
- Branch `feat/gateway-g1-skeleton`, one PR, CI green, merge with your approval. Merging
  redeploys only the planner (unchanged): the gateway isn't deployed until G4.

---

## Done when

- `uvicorn --factory gateway.main:create_app --port 8081` starts with a filled `.env`;
  `curl localhost:8081/healthz` → ok; `curl localhost:8081/nope` → 404 in OpenAI shape with
  an `X-Request-ID` header; missing `GATEWAY_…` vars stop startup with one clear message.
- Quality gate green locally and in CI; gateway tests make no network calls.

## Not in scope

Chat/models routes and the provider adapter (G2), auth (G3), Dockerfile/CI image/CD (G4),
tracing (G13).

## Risks

- **Dependency conflicts** between FastAPI and Streamlit's Starlette/uvicorn: checked with
  `pip install --dry-run` (only `fastapi` and `annotated-doc` are added); CI confirms.
- **Two logging setups** (`app` and `gateway`) drifting apart: accepted; both follow the same
  privacy rule and tests.
