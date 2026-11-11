# LLM Gateway: Architecture

## 1. Components

```
gateway/
  main.py          app factory: builds settings, providers, router, wires middleware + routes
  api/             HTTP layer only: parse request, call services, shape response
    chat.py          POST /v1/chat/completions
    models.py        GET  /v1/models
    health.py        GET  /healthz, /readyz
    admin.py         GET  /admin/usage (G9)
  auth.py          client key → ClientIdentity (G3)
  router.py        alias → ordered candidates (G6)
  resilience.py    timeout, retry, circuit breaker, fallback (G7)
  limits.py        rate limit + token budget, pluggable backends (G8)
  cache.py         exact-match response cache (G11)
  metering.py      usage record + cost (G9)
  providers/       Provider protocol + adapters
    base.py          Provider protocol, normalized request/response types
    openai_compat.py OpenAI-compatible HTTP adapter (G2)
    fake.py          scriptable fake for tests/demos (G2; never routed in production)
  errors.py        GatewayError hierarchy → OpenAI-shaped error responses
  config.py        settings from env + routes.yaml, validated at startup
  observability.py logging/tracing setup (same approach as app/observability.py)
```

**Dependency direction** (enforced by review, and a simple import test from G6):

```
api/  ──►  auth, limits, cache, router, resilience, metering  ──►  providers/
  │                                                                    │
  └──────────────────────────► errors, config, observability ◄─────────┘
```

Adapters never import from `api/`; services never build HTTP responses (they raise
`GatewayError`; `errors.py` turns it into a response). This keeps every service unit-testable
without HTTP.

## 2. Request lifecycle: `POST /v1/chat/completions`

```
Client                Gateway                                                     Provider
  │ POST + Bearer key   │
  ├────────────────────►│ 1 middleware: request ID (accept or create X-Request-ID),
  │                     │   logging context, trace span "gateway.request"
  │                     │ 2 auth: key hash → ClientIdentity            ── 401 ──► (stop)
  │                     │ 3 validate body (allowlisted fields, sizes)   ── 400/413
  │                     │ 4 authorize alias for this client             ── 403 / 404
  │                     │ 5 limits: RPM bucket + token budget (estimate) ── 429
  │                     │ 6 cache lookup (deterministic requests only)  ── HIT → 10
  │                     │ 7 router: alias → [candidate1, candidate2…]
  │                     │ 8 resilience: for each candidate (breaker closed):
  │                     │     call adapter with timeout ───────────────────────────►│
  │                     │     retry on 429/5xx/connect (backoff+jitter)  ◄──────────┤
  │                     │     else next candidate; none left            ── 502/503/504
  │                     │ 9 limits: reconcile estimate with real usage; cache store
  │                     │10 metering: usage record (tokens, cost, latency, status)
  │◄────────────────────┤11 response + X-Request-ID, X-Gateway-Upstream, X-Cache,
  │                     │   x-ratelimit-* headers
```

Order rationale: steps 2–5 are cheap and stop bad or abusive requests **before** any provider
cost; caching (6) sits after limits so cache hits still count toward request rate limits
(but not the token budget).

Phase that introduces each step: 1 (G1), 2 & 4 (G3), 3 (G2 basic, G12 full), 5 & 9-limits (G8),
6 & 9-cache (G11), 7 (G6), 8 (G2 single call, G7 full), 10 (G9), streaming variant of 8–11 (G10).

## 3. Deployment view

```
                 Internet
                    │ HTTPS (public)
                    ▼
     ┌─────────────────────────────┐        asia-south1, project from .env
     │ Cloud Run: sql-planner-apigw│  Streamlit planner UI (exists)
     │ SA: sql-planner-apigw-runtime│
     └──────────────┬──────────────┘
                    │ HTTPS, Bearer client key   (+ Google ID token from G14)
                    ▼
     ┌─────────────────────────────┐
     │ Cloud Run: gateway (G4)     │  FastAPI + uvicorn
     │ SA: gateway runtime SA      │──► Secret Manager: provider key, client registry
     └──────────────┬──────────────┘──► Firestore: limits, budgets, cache, usage (G8+)
                    │ HTTPS, provider key        ──► Cloud Logging / Trace / Monitoring
                    ▼
          OpenAI-compatible provider
```

**Trust boundaries:** (1) internet → planner (public UI); (2) planner → gateway (client key;
from G14 also Cloud Run IAM, gateway not public); (3) gateway → provider (provider key, held only
by the gateway's runtime SA after G5).

Names for the gateway's GCP resources are fixed in G4, built from one prefix like
`scripts/gcp_setup.sh` does today, with the deployer limited to that service.

## 4. Configuration model

| Kind | Where | Examples | Changed how |
|---|---|---|---|
| Secrets | Secret Manager → env vars on Cloud Run; `.env` locally | provider key, client registry (hashes), admin key | new secret version + redeploy |
| Deployment settings | env vars (set by `cd.yml`) | provider base URL, log level, limits backend | redeploy |
| Routing policy | `gateway/routes.yaml` in the repo | aliases, candidates, `max_tokens` caps, prices | PR → CI → CD (reviewed, versioned) |

All config is loaded and **validated once at startup**; invalid config fails the startup
probe, so a bad config never receives traffic (Cloud Run keeps the previous revision serving).
No hot reload: a redeploy is the reload, which keeps behaviour reproducible.

## 5. Statelessness

Gateway instances must be interchangeable: Cloud Run adds and removes them at any time.
State that must be shared (rate-limit counters, budgets, cache, usage aggregates) lives in
Firestore from G8. In-memory backends exist for learning and tests and are marked
**"single instance only"**; they are used in production only with `max-instances=1`.

Per-instance state that is fine to keep: the shared HTTP connection pool, loaded config, and
circuit-breaker state (each instance learns provider health independently: a deliberate
simplification, discussed in G7).
