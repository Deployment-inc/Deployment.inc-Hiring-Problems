# Glossary

Terms used in the problem statements, defined once.

| Term | Meaning |
|---|---|
| **Reference** | A run we publish so you don't have to pay for it — the shipped agent's measured cost, quality and latency. Found under `references/`. Bars are expressed relative to these so they mean something. |
| **Budget class** | The model tier pinned in `MODELS.md`: small hosted models and open-weight models up to ~35B. Every role you control in a submitted run uses budget class only. |
| **Balanced accuracy** | Mean of true-positive rate and true-negative rate. Weights both classes equally; its uncertainty still depends on how many examples each class has. |
| **Cohen's κ (kappa)** | Agreement between two graders corrected for chance. 0 is chance, 1 is perfect. |
| **Expected calibration error (ECE)** | How far a system's stated confidence is from its actual accuracy, averaged over confidence bins. 0 is perfectly calibrated. |
| **Macro-F1** | F1 score averaged equally across classes, so rare intents count as much as common ones. |
| **Goal state** | The exact set of backend rows expected after a case is handled correctly. Task success is a database diff against it, not a judgment. |
| **Gateway ledger** | The record of every model call your service made, kept by the proxy in front of it. Cost and token bars are read from here, never from a figure your own service reports. |
| **Deferral** | Declining to resolve a case and handing it on. Legitimate, but counted: deferred cases are excluded from the resolved denominator, while their spend remains in the numerator. |
| **Behavioural equivalence** | Agreement on the decisions taken — tool called, money moved, escalated, refused — rather than on wording. |
| **Planted regression** | A deliberate degradation we apply at the gateway (stripped system prompt, truncated completions, scrambled tool arguments, unapproved returned model identity) to test whether an eval suite actually catches anything. |
| **p50 / p95 latency** | Median and 95th-percentile response time. The reported quantile method and load must be stated so results can be compared. |
| **Idempotency key** | A client-supplied token that makes a repeated request a no-op instead of a second side effect. |
| **OpenTelemetry (OTel) trace** | A tree of timed spans for one request, exported in a standard format so any tracing backend can display it. |
| **SLO** | Service level objective: the latency, availability or error-rate number you commit to and get paged on. |
| **Harbour** | The loan-servicing agent we wrote for problems 01–04. See [`references/HARBOUR.md`](references/HARBOUR.md). |
