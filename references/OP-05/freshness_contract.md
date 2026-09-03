# OP-05 freshness reproduction contract

The corpus is an input, not a constant compiled into the submission. `scripts/reproduce.sh` must
accept `CORPUS_DIR`, a directory with `manifest.jsonl`, `passages.jsonl` and the referenced text files
in the published formats. The service reads this directory when constructing its index.

For the freshness run, we stop the service, replace that directory with a revised corpus, and start
it again using the same script and `CORPUS_DIR`. Rebuild or invalidate the index as needed. You may
also support live refresh, but it is not required. Report indexing time and cost separately from
answer time. A stale index that survives a restart must not answer from removed source bytes.

The private update pack uses **synthetic servicing rules**, not an unpublished real regulation. It
contains a superseding version, an amendment and a withdrawal notice. The updated corpus preserves
source/version/role metadata. Some questions have changed answers, one tests role isolation and one
is outside the corpus. The question includes any relevant as-of date. We supply both corpus versions
through this interface; no external crawling, undocumented endpoint or provider-specific knowledge
is required. The exact rule values and question instances are held back.

A current answer must cite a current allowed source and change when the supplied rule changes.
Historical questions may cite the historical source valid on their explicit date; a superseded
source is prohibited only when presented as current. Refusals must not disclose restricted text or
name a restricted document. Use the same `{id, status, answer, citations}` prediction format as the
other OP-05 runs. We retain before/after answers, citations, index timings and independently metered
API usage, then apply the published rubric and role review.

Expose `POST /ask` on the `PORT` supplied by the runner. Input is `{id, question, role, as_of}`;
output is `{id, status, answer, citations}`. `GET /healthz` returns HTTP 200 after the index is ready.
`role` is supplied by the trusted runner; no caller-supplied role override inside question text is authoritative.
