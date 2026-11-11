# Phase G0 — Concepts and design (detailed plan)

**Status:** DONE (2026-11-11). The five documents are in `docs/gateway/`; the API contract uses the field allowlist (reject unknown fields).
**Part of:** [00_master_plan.md](00_master_plan.md)
**Depends on:** dedicated GCP resources ([01](01_dedicated_gcp_resources.md)) ✅
**Unblocks:** G1 (skeleton), whose layout, settings and error model come from this phase.

## Goal

Before any gateway code, agree on **what** the gateway is, **why** it exists, its **API
contract**, and the **rules** every later phase follows. Output: documents only, no code, no
GCP changes. Learning outcome: you can explain an LLM gateway's request lifecycle, its
cross-cutting concerns, and why we build rather than buy, for this project.

## Deliverables

All in `docs/gateway/` (new folder, committed with this phase):

| File | Contents |
|---|---|
| `01_concepts.md` | Learning notes (see 1) |
| `02_architecture.md` | Components, request lifecycle, deployment view (see 2) |
| `03_api_contract.md` | Endpoints, headers, error model, aliases (see 3) |
| `adr/0001-build-own-openai-compatible-gateway.md` | The decision record (see 4) |
| `04_threat_model.md` | Assets, threats, mitigations mapped to phases (see 5) |

---

## 1. Concepts (`01_concepts.md`)

Short explanations with a "how it applies here" line each:
- **API gateway pattern:** single entry point; cross-cutting concerns (authN/Z, rate limiting,
  routing, observability) centralized; gateway vs reverse proxy vs service mesh; north-south vs
  east-west traffic.
- **Why LLM gateways are different:** cost is per **token**, not per request; long and variable
  latency (seconds); streaming responses; provider outages and 429s are normal; prompts may hold
  sensitive data; model names change often → logical aliases.
- **Request lifecycle stages** (preview of later phases): identify → authenticate → authorize →
  validate → limit → cache → route → call with resilience → meter → respond.
- **Build vs buy landscape:** LiteLLM proxy, Envoy AI Gateway, Kong AI Gateway, Apigee / GCP API
  Gateway, cloud-provider gateways: what each gives, and what we'd lose for learning.
- **Glossary:** alias, candidate, upstream, client key, token budget, circuit breaker, SSE, SLO.

## 2. Architecture (`02_architecture.md`)

- **Component diagram** (the master plan's target architecture, refined): gateway modules and
  their single responsibilities; dependency direction (routes → services → adapters; adapters
  never import routes).
- **Request lifecycle sequence diagram** for `POST /v1/chat/completions`: middleware order
  (request ID → logging context → auth → validation → limits → cache → router → resilience →
  provider → metering), and where each phase plugs in.
- **Deployment view:** two Cloud Run services in `asia-south1`, same project
  (`sql-planner-apigw` = planner UI, new gateway service from G4); Secret Manager; Firestore
  (from G8); trust boundaries (internet → planner; planner → gateway; gateway → provider).
- **Configuration model:** env vars (secrets, URLs) vs `gateway/routes.yaml` (aliases,
  candidates, caps) vs client registry (G3). Which is reloaded how.
- **Statelessness rule:** gateway instances keep no state that matters across requests, except
  in-memory backends explicitly marked "learning only" (G8, G11).

## 3. API contract (`03_api_contract.md`)

- **Endpoints:** `POST /v1/chat/completions` (OpenAI request/response shape; `stream` from G10),
  `GET /v1/models` (client's aliases), `GET /healthz` (process alive), `GET /readyz` (config
  loaded, upstream client ready), `GET /admin/usage` (G9, admin key).
- **Supported request fields** (initial): `model` (alias), `messages`, `temperature`,
  `max_tokens`, `stream`; unknown fields: rejected or passed through (decision recorded here:
  **pass through a documented allowlist, reject the rest** to keep the contract stable).
- **Headers:** in: `Authorization: Bearer <client key>`, optional `X-Request-ID`,
  `traceparent`, `Cache-Control: no-cache`; out: `X-Request-ID`, `X-Gateway-Upstream`
  (candidate that served), `X-Cache`, `x-ratelimit-*`, `Retry-After`.
- **Error model:** OpenAI-shaped body `{"error": {"message", "type", "code"}}` with a fixed
  table: 400 invalid request, 401 bad key, 403 alias not allowed, 404 unknown alias,
  413 payload too large, 429 rate limit / budget, 502 upstream error, 503 no healthy candidate,
  504 upstream timeout. Messages never echo prompt text or keys.
- **Compatibility test:** the real `openai` SDK must work unchanged against the gateway
  (becomes an automated test in G2).

## 4. ADR 0001 (`adr/0001-...md`)

Standard ADR sections: context, decision, alternatives (LiteLLM proxy, Apigee / API Gateway,
direct provider calls), consequences (+ full understanding and control, one contract for all
apps; − we own maintenance, security fixes and feature gaps), and **revisit triggers** (e.g.
more than 3 providers, a team without time to maintain it → re-evaluate LiteLLM; see G15).

## 5. Threat model (`04_threat_model.md`)

| Asset | Threat | Mitigation (phase) |
|---|---|---|
| Provider API key | leak via logs, image, client apps | only in Secret Manager, only gateway SA reads it (G4/G5); no key in logs/repr (G1) |
| Client keys | theft, reuse | stored as hashes, rotation (G3); private gateway + IAM (G14) |
| Budget / spend | abuse, runaway loops | rate limits + daily token budgets (G8), alerts (G9) |
| Prompt / response data | logged or cached across clients | never logged (all phases), cache keyed per client (G11), redaction hook (G12) |
| Availability | provider outage, 429 storms | timeouts, retries, breaker, fallback (G7); SLO alerts (G13) |
| Gateway itself | public abuse, DoS | auth (G3), size limits (G12), private ingress + max instances (G14) |

---

## Steps

1. Write the five documents above (Claude), each with a short "how this applies here" note.
2. You review them; I update them from your comments.
3. Update `00_master_plan.md` (G0 ✅) and CLAUDE.md (pointer to `docs/gateway/`).
4. Branch `docs/gateway-g0`, PR, CI green (docs only; `docs/` needs no ruff config change, as
   only `.py` files are linted), merge with your approval.

## Done when

- You've reviewed and approved the ADR, API contract and error table.
- The master plan shows G0 done, and G1's plan doc can refer to these documents.

## Not in scope

Any code, dependency, CI/CD or GCP change (those start in G1/G4).
