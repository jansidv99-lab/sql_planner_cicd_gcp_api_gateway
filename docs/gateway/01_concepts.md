# LLM Gateway: Concepts

Learning notes for the gateway built in `plan/v2_api_gateway/`. Each section ends with
**Here:** how the idea applies to this project.

## 1. The API gateway pattern

An **API gateway** is a single entry point that sits in front of one or more backend services.
Clients talk only to the gateway; the gateway forwards each request to the right backend and
applies **cross-cutting concerns** on the way: authentication, authorization, rate limiting,
routing, request/response transformation, caching, logging, metrics and tracing.

Without a gateway, every client re-implements these concerns, slightly differently, and every
client holds credentials for every backend.

| Term | Meaning |
|---|---|
| Reverse proxy | Forwards requests to backends (e.g. nginx). A gateway is a reverse proxy **plus** policy (auth, limits, routing rules). |
| Service mesh | Handles **east-west** traffic (service ↔ service inside a platform) with sidecars. A gateway handles **north-south** traffic (clients → platform). |
| North-south / east-west | Traffic entering/leaving the system vs traffic between internal services. |

**Here:** the "backends" are model providers. Our apps (the SQL planner first) send all LLM
calls to the gateway, which is the only component that knows provider URLs and keys.

## 2. Why LLM gateways are different

A generic gateway counts requests. LLM traffic breaks several of its assumptions:

- **Cost is per token, not per request.** One request can cost 100× another. Limits and
  budgets must count tokens (prompt + completion), estimated before the call and corrected
  after it from the provider's reported usage.
- **Latency is long and variable** (hundreds of ms to tens of seconds). Timeouts, retries and
  concurrency limits have to be sized for that, and retries are expensive.
- **Streaming.** Responses often arrive as Server-Sent Events, token by token. The gateway must
  forward chunks without buffering and still meter usage at the end.
- **Failures are routine.** 429 (rate limited) and 5xx from providers are normal operating
  conditions, not rare incidents → retries with backoff, circuit breakers, fallbacks.
- **Sensitive payloads.** Prompts may contain user or business data. Logging or caching them
  carelessly is a data leak.
- **Model churn.** Model names and prices change often. Clients should ask for a stable
  **logical alias** ("sql-planner-default") that the gateway maps to a real model.
- **Non-determinism.** The same request may produce different answers, so caching is only
  safe for deterministic requests (e.g. `temperature=0`) and is still an approximation.

**Here:** the planner already uses `temperature=0` and records token usage per call
(`app/llm.py`); the gateway takes over limits, budgets, retries and model choice.

## 3. Request lifecycle (preview of the phases)

```
identify → authenticate → authorize → validate → limit → cache → route → call (resilience) → meter → respond
 G1 (ID)       G3            G3          G12        G8      G11     G6        G7 / G2             G9
```

Each stage can **short-circuit** with an error (401, 403, 400/413, 429) before any provider
cost is incurred, which is why the cheap checks come first.

## 4. Build vs buy

| Option | What it is | Gives us | Costs us (for this project) |
|---|---|---|---|
| **LiteLLM proxy** | Open-source OpenAI-compatible LLM proxy | 100+ providers, keys, budgets, fallbacks, caching out of the box | Learning is configuration, not mechanism; another stack to operate |
| **Envoy AI Gateway** | Envoy-based gateway with LLM extensions (Kubernetes) | High performance, token-based limits | Needs Kubernetes; heavy for one Cloud Run app |
| **Kong AI Gateway** | Kong plugins for LLM traffic | Mature gateway + AI plugins | Plugin model, enterprise features paid |
| **Apigee / GCP API Gateway** | Google's managed API management | Managed auth, quotas, analytics | Request-based (not token-based) by default; Apigee is costly; streaming/LLM logic limited |
| **Build our own** | FastAPI service written phase by phase | Understanding of every mechanism; exactly our contract | We own maintenance, security fixes and missing features |

**Here:** we build our own because the goal is learning to production level (ADR 0001).
G15 compares the result against LiteLLM on the same feature list.

## 5. Glossary

| Term | Meaning in this project |
|---|---|
| **Client** | An application calling the gateway (e.g. the SQL planner). Identified by its client key. |
| **Client key** | Secret the client sends as `Authorization: Bearer …`. The gateway stores only its hash (G3). |
| **Alias** | Logical model name a client requests (`sql-planner-default`). |
| **Candidate** | One concrete `{provider, model}` an alias can be served by; an alias has an ordered list (G6). |
| **Upstream / provider** | The model API the gateway calls (today: the OpenAI-compatible endpoint). |
| **Adapter** | Code that talks to one provider type behind a common `Provider` interface (G2). |
| **Token bucket** | Rate-limit algorithm: a bucket refills at a fixed rate; each request takes tokens (G8). |
| **Token budget** | Max LLM tokens a client may use per day (G8). |
| **Circuit breaker** | Stops calling an upstream that keeps failing, retries it after a cool-down (G7). |
| **Fallback** | Trying the next candidate when one fails (G7). |
| **SSE** | Server-Sent Events: the streaming format of `stream: true` responses (G10). |
| **SLI / SLO** | Measured service level (e.g. % non-5xx) and its target (G13). |
