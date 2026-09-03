# OP-05 references — Ask the Policy Book

| File | What it is |
|---|---|
| `corpus/manifest.jsonl` | One line per document: id, title, `role` (visibility), effective date, sha256, text path. |
| `corpus/text/<doc_id>.txt` | The document, passages marked with their section ids. |
| `corpus/passages.jsonl` | The same content passage by passage, if you would rather index that way. |
| `questions_dev.jsonl` | 146 questions **with** `expected_status`, gold answers and gold citations. |
| `questions_heldout.jsonl` | 272 questions, gold withheld. |
| `grader.py` | The official scorer. The exact program we run. |
| `rubric.md` | The judge prompts, verbatim. Nothing about the grading is hidden. |
| `question.schema.json`, `corpus_manifest.schema.json` | The two formats. |
| `manifest.json` | Counts, provenance and licence. |

## The corpus

**391 passages across 34 documents**, from IndiaFinBench (CC BY 4.0, ungated), 164 KB of text.
Everyone retrieves over identical bytes — see the problem statement for why we ship this rather
than have you crawl for it.

Every document carries a `role`: `public` (25 documents), `ops` (3) or `legal` (6). Every question
carries a requester role. A question whose answer lives above the requester's level must be
refused — and refused *correctly*, which is not the same as refused at all. See bar 6.

## The questions

418 total: **329 answerable**, **73 role-blocked**, **16 out-of-corpus**. By category: 174
regulatory interpretation, 92 numerical reasoning, 78 temporal reasoning, 46 contradiction
detection, 16 out-of-corpus, and 12 over Harbour's own internal servicing policy — the layer
where the internal rule is stricter than anything the regulator says.

16 of IndiaFinBench's original 406 questions referred to "the two passages" and are unanswerable
once retrieval takes the passage away. They are dropped, and the manifest says so.

## Historical reference pipeline (pre-revision scorer)

TF-IDF over the shipped passages, top-6 into one budget-class model, no reranker, no query
rewriting, no fine-tuning. These historical numbers use the old per-question citation denominator and incomplete-answer treatment. They must be remeasured before freezing this revision:

| | |
|---|---|
| Coverage (answered / answerable) | 0.8908 |
| Answer correctness | 0.9151 |
| Citation verbatim rate | 0.934 |
| Citation support rate | 0.8384 |
| Out-of-corpus refusal | 1.00 |
| Fabricated citations | **0** |
| Correct refusal on role-blocked | 0.9048 |
| Role violations | **0** |
| Cost | ~1,005 input / ~743 output tokens per question |
| p95 latency | 10.8s at concurrency 12 |

## One thing we got wrong first, and you might too

Our first reference pipeline treated a role-blocked question as *"not in the corpus"*. It reasoned
that saying "you may not see this" reveals the document exists, and that revealing nothing is
safer.

It scored **0.00** on the role-refusal bar, and it deserved to. Telling a compliance officer that
a rule does not exist is a lie with consequences: they will act as though there is no rule. The
right answer names no document, quotes nothing, and still says plainly that something exists which
this requester may not read. Access denied, not file not found.

The role filter is also why the pipeline scores passages *before* filtering rather than after. It
needs to know a better match was withheld in order to say so — but the withheld text never enters
a prompt.

## Running it

```bash
# deterministic checks only, no API key needed
python grader.py --pred preds.jsonl --gold questions_dev.jsonl \
    --corpus corpus/manifest.jsonl --no-judge

# with the rubric judge for answer correctness and citation support
export LLM_BASE_URL=... LLM_API_KEY=... JUDGE_MODEL=...
python grader.py --pred preds.jsonl --gold questions_dev.jsonl \
    --corpus corpus/manifest.jsonl --report report.json
```

Predictions, one object per line:

```json
{"id": "...", "status": "answered|not_in_corpus|not_permitted", "answer": "...",
 "citations": [{"doc_id": "...", "section": "...", "quote": "verbatim from the document"}],
 "cost_usd": 0.0, "latency_ms": 0.0}
```

A quote that does not appear in the cited document fails the verbatim check. The checker uses NFKC, soft-hyphen removal, whitespace collapse and case folding. Citation rates count every citation. Missing answers count against coverage; semantic judge errors make the corresponding metric unavailable. Cost, load latency, full semantic role isolation and freshness require separate reviewer evidence.

## Licence

IndiaFinBench is CC BY 4.0. `manifest.json` records the dataset id and URL.

For the current independent attempt see [CALIBRATION.md](../../CALIBRATION.md). The published [freshness restart contract](freshness_contract.md) specifies how revised corpora are supplied.
