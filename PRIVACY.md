# Privacy

What we collect when you submit, why, who sees it, and how to have it removed.

## What we collect

| Data | Where it lives | Why |
|---|---|---|
| Your GitHub handle and the repository URL and commit you submit | the private intake inbox/form and restricted review records | to identify and evaluate the pinned submission |
| The contents of that repository at that commit | an ephemeral evaluation sandbox; a copy retained privately for the season | to recompute your numbers, run our checks and read your work |
| Your evaluation results and our review notes | private Deployment.inc systems | to decide whether to invite you to a conversation |
| Your name, email address and phone number | the private submission form, stored in Cloudflare D1 | to identify and contact you about your submission |
| Optional LinkedIn URL and your short introduction | the private submission form, stored in Cloudflare D1 | to understand your background and chosen challenge |
| Your submission YAML, selected problem, privacy acknowledgement, receipt ID and submission time | Cloudflare D1 and restricted review records | to record delivery, evaluate the pinned work and handle updates |
| Voluntary accommodation or privacy-request details | the private contact route | to handle your request; do not send credentials or unnecessary sensitive details |
| Hours and development spend, if you choose to report them | your privately submitted file | aggregate reporting on how long problems take; optional |

The challenge form does not ask for a CV, date of birth, photograph or current employer. LinkedIn is optional. Do not include credentials or unnecessary sensitive information in your introduction or uploaded YAML.

## Who sees it

Submissions use separate private repositories and private intake. Other candidates cannot access submissions through our workflow. Source, methods, prompts, experiment logs, individual scores and feedback remain private. Evaluation copies and notes are seen by the Deployment.inc engineers reviewing submissions and by the automated tooling we use to triage them. We do not share submissions with clients or use them in client work. Our infrastructure and model providers process the minimum material needed for evaluation. Internal Slack receives the handle, problem, commit and concise result, not contact details or raw submission contents.

## Automated processing

Scripts recompute your numbers and check required files. Language-model tooling helps us triage and prepare interview questions. Every submission that passes the automated checks is read by an engineer, and no outcome is decided by a model alone.

## Retention

Form entries, uploaded YAML, evaluation copies, results and notes are deleted 12 months after the season closes, unless you join Deployment.inc. Do not submit through public PRs or links: making exposed material private later cannot erase copies already made by others. Use the private contact route for a removal request.

## Your choices

- `leaderboard: false` is required. No individual result or work is published by this workflow. Any later publication requires separate explicit agreement after the season closes.
- Withdraw by emailing contact@deployment.inc with your submission ID at any time. We stop evaluating and delete our copy; you may then revoke reviewer access.
- Ask for access to, correction of, or deletion of anything above by opening a private contact request through [CONTACT.md](CONTACT.md). We respond within ten working days.

Deployment.inc is responsible for this evaluation data. Cloudflare stores form entries in D1. The form and private contact email are listed in [CONTACT.md](CONTACT.md). GitHub hosts the private solution repositories, OpenAI processes model-assisted evaluation, and Slack receives the minimal internal summaries described above. The configured evaluation gateway uses Cloudflare Access. If an evaluation needs a different provider or hosted runtime, we identify it before sending applicant material there.
