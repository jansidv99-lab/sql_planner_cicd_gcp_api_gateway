# LLM Gateway: Threat Model

Scope: the gateway service, its clients (the SQL planner first), its GCP resources and the
provider connection. Method: list assets, then threats per asset (STRIDE-style), then the
mitigation and the phase that delivers it. Reviewed again in G14.

## 1. Assets

| Asset | Why it matters |
|---|---|
| Provider API key | Anyone holding it can spend our money and see our usage |
| Client keys | Impersonating a client uses its budget and permissions |
| Admin key | Reads usage across all clients |
| Spend / token budget | Direct monetary loss |
| Prompt and response content | May contain user or business data |
| Gateway availability | All LLM features of all apps depend on it |
| Usage records | Reveal clients, volumes, costs |

## 2. Trust boundaries

1. Internet → planner UI (public).
2. Planner → gateway (client key; gateway private with Cloud Run IAM from G14).
3. Gateway → provider (provider key).
4. Gateway → GCP services (runtime SA: Secret Manager, Firestore, logging/tracing).
5. GitHub Actions → GCP (keyless WIF, deployer limited to its service).

## 3. Threats and mitigations

| # | Asset | Threat | Mitigation | Phase |
|---|---|---|---|---|
| T1 | Provider key | Leaks via logs, tracebacks, `repr` | Settings hide key in `repr`; never logged; logging privacy test | G1, G12 |
| T2 | Provider key | Leaks from client apps or images | Only in Secret Manager, readable only by the gateway runtime SA; removed from the planner | G4, G5 |
| T3 | Client keys | Stolen from storage | Store SHA-256 hashes only; key shown once at minting | G3 |
| T4 | Client keys | Brute force / timing attacks | High-entropy keys (≥ 32 random bytes); constant-time comparison; 401 without detail | G3 |
| T5 | Client keys | Long-lived leaked key | Revocation + rotation runbook; per-client limits cap the damage | G3, G8, G14 |
| T6 | Spend | Abusive or buggy client loops | Per-client RPM limits + daily token budgets; budget alert | G8, G9 |
| T7 | Spend | Huge prompts / `max_tokens` | Body and message limits; per-alias `max_tokens` cap | G12 |
| T8 | Spend | Retry storms amplify cost | Retry only retryable errors; bounded attempts; circuit breaker | G7 |
| T9 | Content | Prompts/responses in logs or traces | Log metadata only (sizes, status, types); test enforces it | all, G12 |
| T10 | Content | Cache serves one client's answer to another | Cache key includes client ID; per-client opt-out | G11 |
| T11 | Content | PII sent to provider | Optional redaction hook (off by default); policy documented | G12 |
| T12 | Availability | Provider outage / 429 storm | Timeouts, backoff, breaker, fallback candidates, 503 + `Retry-After` | G7 |
| T13 | Availability | Public DoS on the gateway | Auth before work; size limits; private ingress (IAM); `max-instances` cap | G3, G12, G14 |
| T14 | Availability | Bad config or deploy | Startup validation fails readiness; canary + rollback | G1, G14 |
| T15 | Admin data | Unauthorized usage reads | Separate admin key; not exposed in client responses | G9 |
| T16 | Supply chain | Vulnerable dependency or base image | Pinned deps, `pip-audit` in CI, Artifact Registry scanning | G14 |
| T17 | Deploy pipeline | Unauthorized deploys | WIF restricted to this repo's `main`; deployer `run.developer` on the service only | G4 |
| T18 | Errors | Provider error bodies leak details | Fixed error messages; provider details only as error type in logs | G2 |

## 4. Out of scope (handled elsewhere)

- **Prompt injection** against an app's own logic: the app's job (the planner's deterministic
  Reviewer in `app/reviewer.py` is its defense). The gateway does not interpret prompts.
- **Provider-side data handling**: governed by the provider's terms.
- **End-user authentication** in the planner UI: the UI is public by design.

## 5. Residual risks

- A client key held by a compromised client app can be misused up to that client's limits
  until revoked (T5): accepted, bounded by budgets.
- Per-instance circuit breakers react slower than a shared one (each instance learns
  separately): accepted for simplicity (see architecture, statelessness).
- Firestore-based limits allow small overshoot under concurrency: accepted, documented in G8.
