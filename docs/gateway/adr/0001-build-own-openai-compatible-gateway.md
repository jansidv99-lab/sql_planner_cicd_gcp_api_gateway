# ADR 0001: Build our own LLM gateway with an OpenAI-compatible API

- **Status:** Accepted (2026-11-11)
- **Deciders:** project owner, with Claude Code
- **Related:** `plan/v2_api_gateway/00_master_plan.md`, `docs/gateway/03_api_contract.md`

## Context

The SQL planner calls one OpenAI-compatible provider directly (`app/llm.py`) with a provider
key in its own runtime environment. More apps are expected to need LLM access. Without a shared
layer, each app would need its own provider key and would re-implement retries, limits,
budgets, cost tracking and observability.

This project is also explicitly a **learning project** that should reach production quality:
understanding *how* each gateway mechanism works matters as much as having it.

Constraints: Python 3.11, GCP Cloud Run in `asia-south1`, GitHub Actions CI/CD (already in
place), free-tier-first state storage, one provider today.

## Decision

1. **Build our own gateway** as a FastAPI service in this repo (`gateway/`), deployed as its
   own Cloud Run service, phase by phase (G1–G14).
2. **Expose the OpenAI Chat Completions API** (`/v1/chat/completions`, `/v1/models`) with a
   documented field allowlist, so any OpenAI SDK client works by changing `base_url` and key.
3. Clients use **logical model aliases**; the gateway owns the mapping to providers/models.
4. Providers sit behind a **`Provider` adapter interface**, so adding one (e.g. Vertex AI
   Gemini) is a new adapter plus config, without client changes.

## Alternatives considered

| Option | Why not (now) |
|---|---|
| **Keep calling providers directly** | Every app holds provider keys; no central limits, budgets, failover or cost view. |
| **LiteLLM proxy** | Feature-rich and the strongest "buy" option, but we would learn its configuration rather than the mechanisms. Kept as the comparison baseline (G15). |
| **Apigee / GCP API Gateway** | Request-based quotas, limited LLM awareness (tokens, streaming), Apigee cost. |
| **Envoy AI Gateway / Kong** | Need Kubernetes or a plugin platform; heavy for this scale. |
| **Our own API shape** | Every client would need a custom SDK; OpenAI's shape is the de-facto standard. |

## Consequences

**Positive**
- Full understanding and control of every mechanism; behaviour is tested in this repo.
- One contract for all apps; the planner migrates with configuration only (G5).
- Provider keys leave the apps: only the gateway's runtime SA can read them.

**Negative**
- We own maintenance: dependency/security updates, bugs, scaling, on-call runbook.
- Feature gaps vs mature products (fewer providers, no UI) unless we build them.
- One more network hop (tens of ms) and one more service that can fail: mitigated by
  Cloud Run autoscaling, health probes, SLOs and alerts (G13–G14).
- The OpenAI contract ties us to its evolution; we follow it selectively via the allowlist.

## Revisit when

- More than ~3 providers or many provider-specific features are needed, or
- nobody has time to maintain the gateway, or
- a managed product covers our needs at acceptable cost.

Then re-evaluate LiteLLM (or a managed gateway) using the G15 comparison.
