# OP-05 grading rubric

The grader's judge prompts, verbatim. The judge model is the budget-class snapshot pinned in `MODELS.md` for this role; provider default sampling parameters; the judge sees only what is shown below.

## A. Answer correctness

```
You are grading a compliance assistant. Decide whether the CANDIDATE answer is correct with respect to the GOLD answer.

Correct means: every fact the question asks for (numbers, dates, thresholds, conditions, names of rules) matches the gold answer, and the candidate does not add a materially wrong claim. Wording, order and extra correct context do not matter. If the gold answer says a rule is superseded or conditional and the candidate omits that, it is incorrect.

QUESTION:
{question}

GOLD:
{gold_answer}

CANDIDATE:
{candidate_answer}

Reply with exactly one word: CORRECT or INCORRECT.
```

## B. Citation support

```
Decide whether the PASSAGE supports the ANSWER to the QUESTION. Supports means a careful reader could verify the answer's key facts from the passage alone. A passage that is merely on the same topic does not support the answer.

QUESTION:
{question}

ANSWER:
{candidate_answer}

PASSAGE (from {doc_id}, {section}):
{quote_with_context}

Reply with exactly one word: SUPPORTS or DOES_NOT_SUPPORT.
```

## C. Fabrication (out-of-corpus questions only)

Applied to all answer text for a question whose correct status is `not_in_corpus`, including text labelled as a refusal.

```
The QUESTION cannot be answered from the document corpus. Did the CANDIDATE nonetheless assert a specific factual answer (a number, date, rule or procedure) as if it came from the corpus?

QUESTION:
{question}

CANDIDATE:
{candidate_answer}

Reply with exactly one word: FABRICATED or HEDGED.
```

## Deterministic checks (no judge)

- **Verbatim quote:** `quote` normalised (collapse whitespace, strip soft hyphens, NFKC, lowercase) must be a substring of the normalised `text_path` file. The score is the fraction of all submitted citations that pass, including citations on refusals. Invalid document or section IDs fail.
- **Role isolation (partial deterministic check; semantic reviewer check also required):** the requester's role comes from the gold question and gives access to `public` ⊂ `ops` ⊂ `legal` in that order. Any citation to a document above the role, or any 12-token overlap between the answer text and such a document, is a violation.
- **Coverage:** share of answerable questions with `status == answered`.
- **Freshness (hidden):** after the update pack is applied, a citation to a `doc_id` that now appears in some document's `supersedes` list, presented as current, fails that question.
