# Open Problem 05 — Ask the Policy Book

**Category:** Applied · **Track:** Enterprise Knowledge · **Reports to:** Head of compliance · **Harness:** shipped corpus + published question sets

> **Available now:** the corpus (391 passages, 34 documents), the development questions with gold answers, the unlabelled held-out questions, `grader.py`, `rubric.md` (the judge prompts verbatim), both schemas, and qualification targets alongside historical reference scores. Current measurements are in CALIBRATION.md.
> **Not yet published:** the held-out gold answers and the freshness update pack. We run those ourselves.

> "Someone in a branch quoted a 2019 circular at a customer last week. It was withdrawn in 2021. I found out from the customer."

## The Situation

A lender's compliance team fields hundreds of questions a week: the current KYC rule for a minor's account, whether an old circular still applies, what the reporting deadline is, whether internal policy is stricter than the regulator's. The answers exist, spread across regulator documents and an internal policy book, and nobody has time to find them twice.

The head of compliance wants an assistant that answers from those documents only, quotes the exact passage, says "not in the book" when it is not, respects who may see what, and is still right the week after a regulator amends something. Every enterprise asks for "chat with our documents" first. Most of what ships answers confidently from the wrong version of the wrong circular.

## Environment

Two layers, deliberately.

**The regulator layer** is **IndiaFinBench** (CC BY 4.0, ungated). We counted it rather than
quoting its card: **406 expert-written QA pairs over 33 SEBI and RBI documents**, categorised as
174 regulatory interpretation, 92 numerical reasoning, **78 temporal** and **62 contradiction**.
Those last two are why it is the right anchor — contradiction questions where documents disagree
and the answer must say which governs, and temporal questions where the answer depends on what was
in force when. Those behaviours are what separate a compliance assistant from a search box.

We ship the corpus: **391 passages across 34 documents**, the same bytes for everyone. 16 of the
406 questions referred to "the two passages" and become unanswerable once retrieval removes the
passage, so they are dropped and the count is in the manifest rather than quietly padded.

**The internal layer** is Harbour's `policy.md`, our synthetic servicing policy — stricter than the regulator in places, silent in others. Some questions turn on noticing that the internal rule binds first.

**On why we ship the corpus instead of making you crawl for it.** An earlier draft of this
problem had you fetch RBI and SEBI sources yourself from a URL manifest, with crawl politeness
graded from your fetch log. We cut that, and the reason is worth stating because it is the kind of
call you will have to make for clients. RBI content is © RBI with no open licence, their site
returns 418 to non-browser agents, and — fatally for anything graded — every candidate would end
up with a slightly different corpus depending on what was reachable that afternoon, so no two
scores would be comparable. IndiaFinBench is CC BY 4.0 and redistributable. Everyone retrieves
over identical bytes.

**Roles.** Every document carries a visibility label, every question a requester role. A document the requester may not see must never be quoted, paraphrased, summarised, or named as the reason for an answer.

**Freshness.** After scoring your submission we apply a synthetic policy update pack — a superseding version, an amendment and a withdrawal — and re-run a subset. The restart, corpus-input and scoring contract is published in [freshness_contract.md](../references/OP-05/freshness_contract.md); there is no hidden integration API.

## Deliverable

A `POST /ask` service taking `{id, question, role, as_of}` (the published question fields; `role` is the authoritative requester role) and returning an answer, one or more citations, and a verbatim supporting quote per citation — or an explicit refusal. Budget-class models only; any retrieval stack, index or reranker.

> **Season 1 evaluation targets:** The bars below apply to this season. [CALIBRATION.md](../CALIBRATION.md) records current reference attempts and their limits; [RELEASE_MANIFEST.json](../RELEASE_MANIFEST.json) pins the released files. Failed reference attempts do not lower the qualification targets.

## Qualification Bar

Measured on the held-out split by the published `grader.py`. The targets below were informed by a
historical reference pipeline measured on the development split — TF-IDF retrieval over the
shipped passages, top-6 into one budget-class model, no reranker and no fine-tuning. The stricter current per-citation and per-slice checks are not claimed to be cleared by that old run. Its numbers
are in `references/OP-05/README.md` and repeated here so you can see the bar and the reference
together.

1. **Coverage ≥ 0.87** — in-corpus questions answered rather than refused (reference: **0.8908**).
   A system that refuses everything scores zero here, which is the point.
2. **Answer correctness ≥ 0.88** under the published rubric (reference: **0.9151**), reported
   separately for the contradiction and temporal slices; both slices must clear it, not just the
   pooled number.
3. **Citation integrity:** quotes appearing **verbatim** in the cited document at **≥ 0.92**
   (reference: 0.934, match after NFKC, soft-hyphen removal, whitespace collapse and case folding) and supporting the answer under
   the rubric at **≥ 0.82** (reference: 0.8384). Checked on 100% of citations.
4. **Out-of-corpus refusal ≥ 0.95** with **zero** fabricated citations in that set. Our reference
   scores **1.00** and 0 fabrications, so this is the one bar where near-perfect is the
   expectation rather than the stretch: inventing a regulation for a compliance officer is the
   worst thing this system can do.
5. **Zero role violations.** Any quote, paraphrase or named reference to a document the requester
   may not see fails the submission outright. No partial credit. Reference: 0.
6. **Correct refusal on role-blocked questions ≥ 0.87** (reference: **0.9048**). Note what the
   right answer is here: *"you are not permitted to see this"*, **not** *"there is no such
   rule"*. The second is a lie, and a compliance officer told a rule does not exist will act as
   though it does not. Our first reference pipeline made exactly that mistake and scored 0.00 on
   this bar before we fixed it.
7. **Freshness:** on the post-update subset, answers change where the supplied synthetic rule changed, and no
   superseded document is cited as current.
8. **Cost and latency:** at or below the reference, which uses **1,005 input and 743 output tokens**
   per question at a **p95 of 10.8s** at concurrency 12. Stated in tokens rather than dollars so
   the bar does not move when a price list does.

## How this is assessed

| What we run | On what | Produces |
|---|---|---|
| the published `grader.py` | `results/answers.jsonl` — `{id, status, answer, citations: [{doc_id, section, quote}]}` | coverage, correctness overall and per slice, refusal rate |
| the verbatim quote checker and the role checker | `results/answers.jsonl` against the corpus manifest and the question’s authoritative requester role | verbatim rate across all citations (bar ≥ 0.92), role-violation count |
| your service on our machines, after the update pack | the freshness subset | changed answers, superseded citations |
| our cost and latency reader | `results/manifest.json` and the gateway ledger | cost per question, p95 latency |

Nothing is graded from a claim your system makes about itself. It must come up from `scripts/reproduce.sh` on a plain Linux box with no GPU.

## You Decide

- How the corpus is chunked, indexed and versioned, and how "in force on date X" is represented at all.
- How contradictions are resolved and surfaced: pick a winner, present both, or escalate.
- Where the refuse/answer threshold sits and what evidence sets it. That trade-off is the product.
- Whether role filtering happens at retrieval, at generation or both — and how you prove a leak is impossible rather than unlikely.
- What re-indexing after an amendment costs, and whether the client can run it without you.

## Required Analysis

A failure taxonomy of your baseline and which intervention moved which category. The contradiction and temporal slices analysed separately — pooled numbers hide exactly the failures this problem exists to catch. What breaks under the update pack and why. One honest paragraph on what your system does with a document type it has never seen.

## MEMO.md

To the head of compliance. What it answers, what it refuses, what a wrong answer would cost, how they would know it had gone stale, and what keeping it current for a year takes.

## Decision review

Follow [JUDGMENT_REVIEW.md](../JUDGMENT_REVIEW.md). We use your evidence and one new constraint in the existing technical conversation. No additional take-home round is required. Coding-agent use is allowed and disclosed; you own the decisions and their explanation.
