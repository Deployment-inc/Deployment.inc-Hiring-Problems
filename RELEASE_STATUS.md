# Release status — 7 September 2026

**Submissions are open: 7 September–7 December 2026, closing at 23:59 IST.**
Use the [private submission form](https://deployment.inc/hiring-challenges/#submit).
[CONTACT.md](CONTACT.md) names the GitHub reviewer and explains private updates and withdrawals.

The release includes:

- Repaired public scorers, runtime contracts and explicit input/label boundaries.
- Current file hashes in RELEASE_MANIFEST.json and fixed model roles/prices in MODELS.md.
- Measured attempts on all six problems, including private splits. CALIBRATION.md records the
  results, costs and limitations. A failed attempt does not lower the targets or prove that
  every coding agent must fail.
- Valid/invalid submission-format rehearsals for all six problems and isolated Linux runtime checks.
- Private OP-05 update and OP-06 noise packs. Engineering judgment remains part of individual review.
- A fresh private evaluator with tested internal Slack result delivery, independent of the previous
  evaluator. Automated output is not a hiring decision.
- A private Cloudflare D1 form with required-field validation, bounded YAML uploads, retry-safe
  receipts and no public response listing. A synthetic form submission was checked end to end.

All numeric bars remain the published targets. The model roles and datasets pinned in the release
manifest define the comparison basis. Changes follow EVALUATION_PROTOCOL.md and are recorded in
CLARIFICATIONS.md. Reviewers verify availability before evaluation; infrastructure outages leave
results pending. Submission receipt does not mean repository access or qualification is approved.
