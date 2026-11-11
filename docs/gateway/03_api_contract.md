# LLM Gateway: API Contract (v1)

The gateway speaks the **OpenAI Chat Completions API**, so an OpenAI SDK client works by
changing only `base_url` and the key:

```python
client = openai.OpenAI(base_url="https://<gateway>/v1", api_key="<client key>")
client.chat.completions.create(model="sql-planner-default", messages=[...])
```

## 1. Endpoints

| Method + path | Auth | Purpose | Phase |
|---|---|---|---|
| `POST /v1/chat/completions` | client key | Chat completion (non-streaming; `stream: true` from G10) | G2 |
| `GET /v1/models` | client key | Aliases this client may use, OpenAI list shape | G2 (all), G6 (per client) |
| `GET /healthz` | none | Liveness: process is up | G1 |
| `GET /readyz` | none | Readiness: config loaded, HTTP client ready | G1 |
| `GET /admin/usage` | admin key | Usage and cost per client/alias/day | G9 |

Until G3, the chat and models endpoints are only run locally (no auth yet).

## 2. Request fields (`POST /v1/chat/completions`)

**Rule: forward a documented allowlist, reject everything else** with 400. This keeps the
contract stable and stops clients depending on provider-specific behaviour by accident.

| Field | Type | Notes |
|---|---|---|
| `model` | string, required | A gateway **alias**, never a provider model name |
| `messages` | array, required | `{role: system\|user\|assistant, content: string}`; limits on count and size (G12) |
| `temperature` | number 0–2, optional | |
| `max_tokens` | integer ≥ 1, optional | Capped per alias (G12) |
| `top_p` | number 0–1, optional | |
| `stop` | string or array (≤ 4), optional | |
| `stream` | boolean, optional | `true` supported from G10; before that → 400 |
| `stream_options` | object, optional | Only `include_usage` (G10) |
| `user` | string, optional | Client's own end-user ID, recorded in metering (hashed) |

Not supported in v1 (→ 400 `unsupported_parameter`): tools/function calling, `n > 1`, images,
audio, `logprobs`, `response_format`. Adding one is a contract change (new ADR or doc update).

## 3. Response

Same shape as OpenAI (`id`, `object`, `created`, `model`, `choices`, `usage`), with:
- `model` = the **alias** the client asked for (the real model is in `X-Gateway-Upstream`), so
  clients never couple to provider model names;
- `usage` always present (needed for metering); if the provider omits it, the gateway estimates
  it and sets `X-Gateway-Usage: estimated`.

## 4. Headers

**Request (from client):**

| Header | Required | Purpose |
|---|---|---|
| `Authorization: Bearer <client key>` | yes (from G3) | Client identity |
| `X-Request-ID` | no | Correlation ID; generated if absent (≤ 128 chars, `[A-Za-z0-9._-]`) |
| `traceparent` | no | W3C trace context; joins the caller's trace (G13) |
| `Cache-Control: no-cache` | no | Skip cache lookup (G11) |

**Response (to client):**

| Header | Purpose | Phase |
|---|---|---|
| `X-Request-ID` | Same ID as in the gateway logs | G1 |
| `X-Gateway-Upstream` | `provider/model` that served the request | G2 |
| `X-Gateway-Attempts` | Number of upstream attempts (retries + fallbacks) | G7 |
| `X-Cache` | `HIT` or `MISS` | G11 |
| `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens` | Current limits | G8 |
| `Retry-After` | Seconds to wait (with 429/503) | G7/G8 |

Provider response headers are **not** forwarded (they can reveal the provider, account or
internal IDs).

## 5. Error model

Body (OpenAI shape, so SDKs raise the right exception class):

```json
{"error": {"message": "Unknown model alias 'x'", "type": "invalid_request_error",
           "code": "model_not_found", "request_id": "…"}}
```

| HTTP | `type` | `code` (examples) | When | Retry? |
|---|---|---|---|---|
| 400 | `invalid_request_error` | `invalid_body`, `unsupported_parameter` | Bad JSON, unknown/invalid field | no |
| 401 | `authentication_error` | `invalid_api_key` | Missing, unknown or revoked key | no |
| 403 | `permission_error` | `model_not_allowed` | Alias not allowed for this client | no |
| 404 | `invalid_request_error` | `model_not_found` | Unknown alias | no |
| 413 | `invalid_request_error` | `payload_too_large` | Body or messages over limits | no |
| 429 | `rate_limit_error` | `rate_limited`, `token_budget_exceeded` | Client over RPM or daily budget | after `Retry-After` |
| 502 | `upstream_error` | `upstream_bad_response` | Provider error after retries | yes, later |
| 503 | `upstream_error` | `no_healthy_upstream` | All candidates' breakers open | after `Retry-After` |
| 504 | `upstream_error` | `upstream_timeout` | Deadline passed | yes, later |
| 500 | `server_error` | `internal_error` | Gateway bug | yes, later |

Rules:
- Messages never contain prompt text, keys or provider error bodies (provider details go to
  logs as error **type** only).
- Provider 4xx caused by the request itself (e.g. context length) map to 400 with code
  `upstream_rejected_request`; provider 401/403 (our key is wrong) map to 502, never to
  401, so clients don't think *their* key is bad.

## 6. Aliases

- Clients request aliases such as `sql-planner-default`. `gateway/routes.yaml` maps each alias
  to ordered candidates (G6). Until G6, one alias maps to the `MODEL` env var.
- Alias names: lowercase, `[a-z0-9-]`, stable; changing the underlying model is a config change,
  not a client change.

## 7. Compatibility guarantee

An automated test (from G2) drives the gateway with the **real `openai` SDK** (pinned in
`requirements.txt`) against the fake provider: success, every error row above mapping to the
expected SDK exception, and (G10) streaming.
