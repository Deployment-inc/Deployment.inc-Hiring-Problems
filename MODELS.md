# Season 1 model pins — launch 7 September 2026

These fixed reference roles were verified through the evaluation gateway on 6 September 2026.
Every submitted run names an exact snapshot or immutable open-weight revision, its provider/host,
and the public price source used in its manifest. Aliases alone are not reproducible pins.

## Fixed reference roles

| Role | Exact snapshot | Input $/M | Output $/M |
|---|---|---|---|
| Harbour starter and OP-02 retiring configuration | `gpt-4.1-mini-2025-04-14` | 0.40 | 1.60 |
| OP-02 control successor and OP-04 reference judge | `gpt-5-mini-2025-08-07` | 0.25 | 2.00 |
| OP-05 generation reference | `gpt-5-mini-2025-08-07` | 0.25 | 2.00 |
| OP-05 grader judge | `gpt-4.1-mini-2025-04-14` | 0.40 | 1.60 |

The prices are USD per million uncached text tokens, verified on 6 September 2026 from the official
[GPT-4.1 mini page](https://developers.openai.com/api/docs/models/gpt-4.1-mini) and
[GPT-5 mini page](https://developers.openai.com/api/docs/models/gpt-5-mini). They are the fixed rates
for these reference comparisons. Cache discounts are not credited to benchmark cost. The actual
snapshot IDs were returned by the gateway; [CALIBRATION.md](CALIBRATION.md) contains measured runs.

The archived OP-04 trajectory files identify their generating model families as `gpt-4.1-mini` and
`gpt-5-mini`, including the private set. Those historical files do not establish exact dated provider
snapshots. Their fixed bytes and trusted labels are the judging dataset; they are not a promise that
regenerating a trajectory with a current alias produces identical text.

## Candidate model choices

Every model role controlled by the submission must remain budget class: small hosted models in a
provider's mini/nano/Flash/Haiku tier, or open-weight models up to approximately 35B parameters.
This applies to generators, planners, critics, routers, verifiers and fallbacks. Embeddings and
rerankers are allowed unless a problem says otherwise; disclose and meter their API cost too.
Fine-tunes remain budget class only when the underlying model qualifies and training data is
disclosed without any held-out benchmark material.

Candidates may choose a different budget-class model. Supply its exact identifier, public price
source with retrieval date, and input/output rates in the run manifest. The reviewer verifies and
pins those rates before comparing costs; unsupported or unpriced usage remains pending and cannot
be assigned a guessed default price. The two fixed reference models use the table above throughout
the season. Any other model uses its disclosed, independently verified rate consistently across
that submission's reference/candidate comparisons. Compute and API spend are disclosed separately,
including compute received through credits; see [FREE_CREDITS.md](FREE_CREDITS.md).

`contract_check/prices.yaml` contains only the verified exact IDs above. Use `--prices` to supply
an independently verified table for other choices. Model-name prefixes and a `default` price are
not accepted as evidence of a model's cost.

## Retirement handling

The official GPT-5 mini page labels its old dated snapshot deprecated, although authenticated
calls succeeded in this review. This is present-access evidence, not a guarantee of season-long
availability. If a fixed snapshot becomes unavailable, Deployment.inc announces a measured
replacement within five working days. Already submitted results on the old snapshot remain valid;
new scoring uses a published replacement reference, with no silent threshold change.

OP-02's deprecation notice is a synthetic scenario. It does not assert that a provider announced
retirement on the fictional schedule. Reviewers check gateway availability before each evaluation.
An infrastructure outage leaves the affected evaluation pending; it is not a candidate failure.
Changes to a required snapshot are disclosed through the replacement process above.
