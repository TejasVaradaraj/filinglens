# FilingLens Roadmap

This is the build order for FilingLens: what to build, in what order, why that order makes sense, and which AI engineering skills each step teaches you. There are no dates in it. You move to the next phase when the current phase's **"Done when"** checklist is met, however long that takes.

It assumes you're starting from zero AI engineering knowledge. Every new term is explained the first time it shows up, and there's a glossary at the bottom.

---

## How to read this

Each phase has the same parts:

- **Goal**: what this phase is for, in one sentence.
- **Why now**: why it comes at this point and not earlier or later.
- **Steps**: what to build, in order.
- **What you'll learn**: the AI engineering ideas this phase teaches, in plain words.
- **Done when**: the checklist that has to be true before you move on.
- **Interview story**: what you'll be able to say about this phase once it's finished.

### The one rule behind the whole order

> **Measure first, then build, then measure again.**

Most student AI projects get built like this: write a lot of code, try a few questions, decide it "seems good." Nobody can tell whether it actually works, so recruiters learn nothing from it.

FilingLens gets built the other way. You build a **scoreboard** first (the "eval"), then add one piece at a time and check whether the score went up. That's how real AI teams work, and it's the biggest thing that will set this project apart.

---

## The big picture (read this first)

### What FilingLens does, in plain words

You ask: *"What was Nike's gross margin in 2023 and why did it change?"*
FilingLens:
1. Finds the right pages in Nike's annual report (the "10-K").
2. Pulls out the exact numbers it needs (revenue, cost of sales).
3. Does the math in **Python**, not in the AI's head.
4. Writes a short answer where every number links to the page it came from.
5. Checks its own answer. If it can't back a number up, it says "not disclosed" instead of guessing.

### The two halves of the system

```
HALF 1: INGESTION  (runs once per filing, ahead of time)
  Get filing --> Break into sections & tables --> Cut into chunks --> Store in database
                                                                       (text + "meaning vectors")

HALF 2: QUERY  (runs every time someone asks a question)
  Question --> Find the right chunks --> AI pulls out exact numbers --> Python does the math
           --> AI writes answer with citations --> Checker verifies every number --> Show user
```

Almost every phase below builds or improves one box in this diagram.

### The phases at a glance

| # | Phase | What it gives you | Version |
|---|---|---|---|
| 0 | Setup + talking to an LLM | You can call an AI model from code and understand what's going on | (prep) |
| 1 | The scoreboard (evals) + 2 dumb baselines | A number that says how good any version is | v1 |
| 2 | Reading filings properly (ingestion + parsing) | Clean sections and tables in a database | v1 |
| 3 | Finding the right pages (retrieval) | The system pulls the correct pages for a question | v1 |
| 4 | Getting exact numbers + doing math in code | Correct numbers, correct math | v1 |
| 5 | Answers with citations + knowing when to refuse | Trustworthy answers, served by an API | v1 |
| 6 | Fix-the-biggest-failure loop + ship v1 | Deployed app, README, resume bullet #1 | **v1 ✅ start applying** |
| 7 | Multi-filing reasoning + rigor | Comparisons, verifier, tracing, evals in CI | v2 |
| 8 | Production features | Job queue, "what changed", security, cloud | v3 |

---

## Phase 0: Setup and learning to talk to an LLM

**Goal:** be comfortable calling an AI model from Python and understand the basic controls before building anything real.

**Why now:** every later phase is "call an LLM, but carefully." If the basics are fuzzy, everything after them will be too.

**Steps**
1. Finish project setup: a Python virtual environment, install packages, put your API key in `.env` (the repo is already scaffolded for this), and get `pytest` passing.
2. Write a tiny script that sends one question to the LLM and prints the answer.
3. Play with it on purpose:
   - Change the **system prompt** (the instructions that set the AI's role) and watch the answers change.
   - Change **effort** (how much the model "thinks" before answering: low / medium / high). Ask the same hard question at each level and compare the answers, the token counts and the cost. Also ask one question 5 times at the same setting and notice the answers aren't identical. (Claude Haiku 5.5 doesn't let you change temperature, so effort is the setting to experiment with.)
   - Print the **token counts** (tokens are word-pieces; you pay per token) and work out what one call cost.
   - Paste a page of a 10-K into the prompt and ask about a number in it. Then ask it to do math on two numbers from that page. Watch where it gets things wrong.
4. Download the **FinanceBench** dataset (150 real analyst questions about real filings, each with a correct answer and the page the answer comes from). Read about 10 questions and open their PDFs by hand. You need a feel for what the questions look like.

**What you'll learn**
- **LLM API basics**: messages, roles (system / user / assistant), the model's reply.
- **Tokens, context window, and cost**: the model can only "see" a limited amount of text at once (the context window), and you pay for every token in and out.
- **Effort / reasoning and non-determinism**: more thinking costs more tokens but can improve hard answers. The same question can give different answers, which is exactly why we measure instead of eyeballing.
- **Why LLMs are bad at arithmetic and long documents**: you'll see it happen yourself, and that's the reason for this whole project.

**Done when**
- [ ] You can call the model from code and print cost per call.
- [ ] You've read ~10 FinanceBench questions and their source pages by hand.
- [ ] You can explain in your own words what a token, a context window and effort are.

**Interview story:** "Before building, I tested the raw model on filings and saw it miscount numbers and make up figures. That's what drove the design."

---

## Phase 1: Build the scoreboard (evals) and two dumb baselines

**Goal:** have a script that runs any version of the system over a set of questions and spits out a score. Then score two simple "dumb" systems so you have something to beat.

**Why now:** if you build features first, you'll never know whether they helped. The scoreboard comes first so every later change can be measured. This is the single most valued skill in AI engineering interviews right now.

**Steps**
1. **Split the questions.** Put ~100 FinanceBench questions in a **dev set** (you look at these, debug on them, tune on them) and ~50 in a **test set** (you don't look at these; you run them only when reporting a final number). Using the test set to tune is cheating, and interviewers ask about it.
2. **Start your own question file.** Add questions FinanceBench doesn't cover well: multi-year comparisons, and questions whose correct answer is "the filing doesn't say" (these test whether the system refuses properly). Start with a few; it grows over time.
3. **Write the eval runner.** For each question it:
   - runs the system,
   - records the answer, how long it took, and what it cost,
   - **scores it**: numbers count as correct if they're within ~1% of the right answer; text answers get graded by a second LLM call using a rubric (this is called **LLM-as-judge**),
   - writes everything to a results file so you can compare runs.
4. **Check the judge.** Grade about 20 answers yourself and compare with the LLM judge. If you disagree a lot, fix the judge's rubric. A judge you haven't checked can't be trusted.
5. **Baseline A, "naive RAG"** (RAG = Retrieval-Augmented Generation: find relevant text, then give it to the LLM to answer from):
   - pull plain text out of the PDF (simplest tool possible),
   - cut it into fixed-size pieces (say every 500 words),
   - turn each piece into an **embedding** (a list of numbers that captures the piece's meaning) and store them,
   - for a question, find the ~5 pieces whose meaning is closest and give them to the LLM to answer.
6. **Baseline B, "long context"**: stuff the whole filing into the prompt and ask the question. Simple, slow, expensive.
7. Use the **same LLM** for both baselines (and later for FilingLens too). Otherwise the comparison isn't fair.
8. Create `CHANGELOG.md` and write the first lines: date, version, scores for both baselines.

**What you'll learn**
- **Evals / golden sets**: a fixed set of questions with known answers that you score against again and again.
- **Dev/test split and overfitting**: why tuning on the same questions you report makes your number a lie.
- **LLM-as-judge**: using an LLM to grade answers, and its weak spots (it favors long answers, can be fooled, needs a clear rubric).
- **Baselines**: you can't claim "better" without something to be better than.
- **Your first RAG system and first embeddings**: the core idea everything else improves on.
- **Experiment tracking**: logging every run so results can be reproduced.

**Done when**
- [ ] One command runs the eval and prints a score.
- [ ] Both baselines are scored on the dev set and written in `CHANGELOG.md`.
- [ ] You've hand-checked the LLM judge on ~20 answers.

**Interview story:** "Before writing any features I built an eval harness and scored two baselines with the same model, so every later change has a measured before and after."

---

## Phase 2: Reading filings properly (ingestion and parsing)

**Goal:** turn messy PDF/HTML filings into clean, labeled sections and real tables (rows, columns, units) stored in a database.

**Why now:** in Phase 1 you'll have seen the naive baseline fail because tables turned into garbage text and numbers lost their units. Retrieval and extraction can't be any better than the data they work from, so fixing the input comes before anything else.

**Steps**
1. **Pick a parser by measuring.** Try two existing parsing libraries (for example Docling and PyMuPDF/pdfplumber) on ~10 FinanceBench PDFs. Check by eye and with simple checks: are tables still tables? Are page numbers kept? Pick the better one. Don't write your own parser unless the evals show you need to. **Timebox this.** Parsing can eat weeks.
2. **Split each filing into sections.** 10-Ks have standard parts: Item 1A (Risk Factors), Item 7 (MD&A, management explaining the results), Item 8 (Financial Statements). Tag every piece of text with which section it's from.
3. **Handle table details.** "In millions" vs "in thousands", negative numbers written as `(1,234)`, headers that span two rows, footnotes. Store each table with its unit, scale and time period.
4. **Database setup.** Postgres in Docker Compose (Docker runs the database in a container, so you don't install it by hand), with the `pgvector` extension for storing embeddings. Tables for: filings, sections, tables, chunks.
5. **SEC EDGAR fetcher.** Code that downloads a company's filings from the SEC's free API. Follow the SEC's rules: declare a User-Agent, slow down requests, cache files locally. Make it **idempotent** (running it twice doesn't create duplicates). The evals use FinanceBench PDFs, so this part is for the real product, which is why it comes last in this phase.
6. Write unit tests for the tricky parsing cases (the parentheses negatives, the unit labels).

**What you'll learn**
- **Document parsing and table extraction**: the unglamorous part where most real AI systems quietly fail.
- **Metadata design**: labeling every piece of data (company, year, form type, section, page) so you can filter on it later.
- **Data pipelines**: turning raw input into clean, stored data reliably and repeatably.
- **Working with external APIs**: rate limits, retries, caching.

**Done when**
- [ ] Parsed output spot-checked on several filings; tables keep their rows, columns and units.
- [ ] Negative numbers and "in millions/thousands" are handled correctly.
- [ ] Re-running ingestion creates no duplicates.

**Interview story:** the "hardest bug" question usually gets answered here. Keep a short note every time a table breaks in a weird way.

---

## Phase 3: Finding the right pages (retrieval)

**Goal:** for any question, pull back the few chunks that actually contain the answer, from the right company and the right year.

**Why now:** you now have clean data. Retrieval is the "R" in RAG; if the right page isn't found, nothing after it can save the answer. FinanceBench tells you the correct page for each question, so you can measure retrieval on its own.

**Steps**
1. **Add a retrieval metric to the eval: recall@k.** For each question, did the correct page show up in the top *k* retrieved chunks (say k = 5)? This lets you judge retrieval separately from the final answer.
2. **Smart chunking.** Split by section and table, never in the middle of a table, and attach the table's header to every chunk of rows so each chunk makes sense on its own. Try 2–3 chunk sizes and pick by recall@k.
3. **Embeddings into pgvector.** Store a meaning-vector per chunk. This is **semantic search**: finding text with similar *meaning*.
4. **Keyword search (BM25 / Postgres full-text).** Finds exact words. Finance needs this: "diluted EPS" must match exactly, and meaning-search alone can miss it.
5. **Metadata filters first.** Before searching, restrict to the right ticker, year, form and section. The original FinanceBench paper found that mixing all filings together made accuracy collapse because it grabbed the wrong company/year.
6. **Hybrid search.** Run keyword and semantic search, then merge the two ranked lists (a simple standard method is called **reciprocal rank fusion**).
7. **Ablation table.** Turn each piece on and off (filters, keyword, semantic, hybrid) and record recall@k for each. This table proves which parts actually matter.

**What you'll learn**
- **Embeddings and vector search**: how "meaning" gets turned into numbers and searched.
- **Keyword search (BM25)** and why it's still needed alongside vectors.
- **Hybrid retrieval**: combining both.
- **Chunking tradeoffs**: chunks that are too small lose context; too big and they bury the answer.
- **Retrieval metrics** (recall@k, MRR) and **ablation studies**: measuring which component helped how much.

**Done when**
- [ ] recall@k clearly beats the naive baseline's retrieval.
- [ ] You have an ablation table and can explain each number.

**Interview story:** "Pure vector search missed exact financial terms; adding BM25 plus metadata filters took recall@5 from X to Y. Here's the ablation."

---

## Phase 4: Getting exact numbers and doing math in code

**Goal:** the LLM's only job is to *find and copy* the numbers. Python does all the calculating.

**Why now:** retrieval now finds the right pages. The next biggest failure type is wrong numbers: wrong units, wrong period, or arithmetic done "in the model's head."

**Steps**
1. **Define the shape of an extracted number** using Pydantic (a Python library for defining and checking data shapes): value, unit (USD, shares, %), scale (thousands/millions), period (FY2023, Q3 2024), and the ID of the chunk it came from.
2. **Structured extraction.** Ask the LLM to return JSON in exactly that shape (**structured outputs**). Check it with Pydantic. If the JSON is broken or missing fields, retry automatically.
3. **The calculator.** Plain Python functions for gross margin, operating margin, growth rates, ratios, and so on. First convert everything to the same unit and scale. Handle fiscal years that don't match calendar years. Write unit tests for every function.
4. **Tool use / function calling.** Let the LLM call your calculator as a "tool": the model decides "I need gross margin from these two numbers," your code runs the math, and the model gets the exact result back. The model never does the arithmetic itself.
5. Rerun evals. The "math error" and "unit error" counts should drop.

**What you'll learn**
- **Structured outputs / JSON schemas**: getting reliable, machine-readable output from an LLM instead of free text.
- **Validation and retries**: handling the LLM's mistakes in code.
- **Tool use / function calling**: the LLM asks your code to do something. This is the building block of all "AI agents."
- **The LLM-vs-code boundary**: deciding what the model should do (understanding language) vs what code should do (anything that has to be exactly right).

**Done when**
- [ ] The calculator has passing unit tests.
- [ ] Math and unit errors on the dev set have dropped, with numbers in `CHANGELOG.md`.

**Interview story:** "The LLM never does arithmetic. It extracts typed values with their sources, and a tested Python engine computes. That removed an entire class of errors."

---

## Phase 5: Answers with citations, and knowing when to refuse

**Goal:** a final answer where every number is linked to its source and automatically checked, plus a system that says "not disclosed" instead of making something up.

**Why now:** you have correct numbers and correct math. Now you turn them into an answer a person can trust, and make it reachable through an API.

**Steps**
1. **Answer writer.** The LLM writes a short answer but can only refer to numbers by their source ID, never type a number freely. Your code fills in the actual numbers.
2. **Simple number checker.** After the answer is written, check in code that every number in it appears in the chunk it cites (after converting units). If one doesn't, regenerate or refuse.
3. **Refusal.** If the evidence isn't there, answer "not disclosed" plus what was searched. Score this on your "not disclosed" questions, and also count **over-refusals** (refusing when the answer *was* there). Both matter.
4. **Hallucination rate.** Add it to the eval: the share of answers that are *wrong and not refused* (confidently wrong). This is the number that matters most for trust.
5. **API.** A FastAPI endpoint that takes a question and **streams** the answer back as it's generated (using Server-Sent Events, so the user sees text appearing instead of waiting).
6. **Minimal interface.** A simple CLI or web page showing the answer, the citations, and a "show the work" panel (inputs + formula).

**What you'll learn**
- **Grounding**: forcing answers to be based only on retrieved evidence.
- **Citation verification** and **hallucination measurement**.
- **Refusal calibration**: balancing "refuse when unsure" against "don't refuse everything."
- **Prompt design**: writing instructions that constrain the model's behavior.
- **Serving an LLM app**: APIs and streaming.

**Done when**
- [ ] Hallucination rate is measured and recorded.
- [ ] Refusal accuracy and over-refusal rate are reported.
- [ ] You can ask a question through the API and see a streamed, cited answer.

---

## Phase 6: The failure loop, then ship v1

**Goal:** push the score up by fixing whatever's failing most, then ship it publicly.

**Why now:** all the pieces exist. This is where the system gets *good*, and where your best interview story comes from.

**Steps**
1. **Bucket every dev-set failure.** Look at each wrong answer and label why: wrong retrieval, bad table parse, unit error, math error, hallucination, bad refusal.
2. **Fix the biggest bucket. Rerun. Repeat.** One change at a time, with a line in `CHANGELOG.md` each time (what changed, old score, new score).
3. **Run the test set once** and record that number. That's the one you put on your resume.
4. **UI**: a small Next.js page where you pick a company, ask a question, and see the answer, citations and show-work panel.
5. **Deploy** to an easy host (Render, Fly or Railway) so there's a live link.
6. **README**: what it is, architecture diagram, the 3-way results table (naive RAG vs long context vs FilingLens, same model), the changelog, and honest limitations.

**What you'll learn**
- **Error analysis**: the core loop of AI engineering. Read failures, group them, fix the biggest group.
- **Iterating from data instead of guesses.**
- **Communicating results**: the README is part of the product.

**Done when (v1 ✅)**
- [ ] Beats both baselines on the dev set.
- [ ] One held-out test number recorded.
- [ ] Live deployed link works.
- [ ] A stranger understands the README in 2 minutes.

**➡ Put v1 on your resume and start applying here.** Keep building while you apply.

**Interview story:** "Here's my changelog: each fix, which failure bucket it targeted, and the score after. Biggest jump came from X."

---

## Phase 7 (v2): Multi-filing reasoning and engineering rigor

**Goal:** handle questions across several years and companies, verify answers more thoroughly, and run the system like a professional team would.

**Why now:** v1 handles one filing at a time. Real analysts compare. These steps are also the "strong signal" skills that set candidates apart.

**Steps, in this order (each one helps the next):**
1. **Tracing and cost/latency logging** (Langfuse or OpenTelemetry). Record how long each stage takes and what each call costs. Comes first so every later change can be judged on speed and cost, not just accuracy.
2. **Reranker.** After retrieval returns ~30 candidates, a second, more careful model reorders them by relevance. Measure how much recall@k goes up and how much latency it adds.
3. **Query planner (your first "agent").** The LLM reads the question, decides its type (lookup / calculation / comparison / explanation), and splits it into sub-questions. "Compare operating margin for AMD, Intel and NVIDIA over 3 years" becomes 9 small lookups. Run them in parallel with `asyncio` and join the results in code into a table where every cell is sourced.
4. **Full citation verifier.** Extend the number checker: for text claims (not just numbers), use an LLM judge to check that the cited passage actually supports the claim. Regenerate or refuse on failure. Measure **citation precision** (what share of citations actually support their claim).
5. **XBRL cross-check.** The SEC publishes official tagged numbers for every company. Compare your extracted headline numbers to them and flag mismatches.
6. **Caching and model routing.** Cache embeddings and repeated questions. Use a cheaper, faster model for easy jobs (classifying, extracting) and the strong model only for writing answers. Report cost per question before and after.
7. **Evals in CI.** A GitHub Action runs the eval on every pull request, posts the score, and blocks merging if the score drops.
8. **Earnings call transcripts** as a second document type.

**What you'll learn**
- **Reranking**: two-stage retrieval, a fast first search plus a careful second sort.
- **Query decomposition and planning / agentic orchestration**: an LLM breaking a task into steps and coordinating tools.
- **LLM-as-judge for verification** (not just grading).
- **Observability**: tracing, latency and cost per stage.
- **Cost optimization and model routing**: a frequent interview topic.
- **CI for AI systems**: catching quality regressions automatically.

**Done when (v2 ✅)**
- [ ] Comparison questions work end to end with sourced tables.
- [ ] Citation precision is measured.
- [ ] CI posts eval scores and shows score history.

**Interview story:** "Reranking raised recall@5 from X to Y at +Z ms; routing cut cost per question by N% with no accuracy loss; CI blocks any PR that regresses the score."

---

## Phase 8 (v3): Production features

**Goal:** make it look and behave like a real product. **These are ordered by resume value. Stop whenever you run out of time.** Each one can ship on its own.

1. **Bulk ingestion with a job queue.** Ingest e.g. the S&P 500's latest 10-Ks using a background queue (Redis + RQ or Celery). Retries, a "dead-letter" queue for jobs that keep failing, progress tracking, no duplicates. Report throughput and cost per filing.
2. **"What changed" mode.** Line up this year's Risk Factors/MD&A against last year's, paragraph by paragraph, and label each as new / removed / reworded. Includes **auto-update**: a scheduled job checks EDGAR for new filings.
3. **Citation viewer + Excel export.** Clicking a citation opens the filing at the highlighted spot; any answer table downloads to Excel with a sources column.
4. **Prompt-injection defense.** When users upload their own documents, someone could hide instructions in them ("ignore your rules and…"). Treat document text strictly as data, and test with deliberately malicious documents.
5. **Auth + workspaces.** User accounts, saved questions, private uploads kept separate per user (multi-tenancy).
6. **AWS deploy, monitoring, load test.** Run on AWS (ECS/RDS/S3), add error monitoring (Sentry), load-test with many simultaneous users and report p95 latency (the time 95% of requests finish under).
7. **Write-up + 2-minute demo video** built around the eval story.

**What you'll learn**
- **AI security / guardrails**: prompt injection is a top concern for companies shipping LLM features.
- **Scaling data pipelines**: queues, retries, idempotency.
- **Production engineering**: auth, cloud, monitoring, load testing.

**Done when (v3 ✅):** every resume bullet has a real, measured number behind it.

---

## Optional stretch goals (only after v2)

Pick at most one. These hit areas the main plan skips:
- **Fine-tune a small model** for routing or extraction and compare it to the API model on cost and accuracy.
- **Fine-tune an embedding model or reranker** on FinanceBench-style question/page pairs and measure the retrieval gain.
- **Expose FilingLens as an MCP server** (a standard way for AI assistants to use outside tools) so tools like Claude can query filings through it.

---

## What internships care about most, and where you get it

| Priority | Skill | Phase |
|---|---|---|
| ⭐⭐⭐ Must have | Evals, golden sets, LLM-as-judge, error analysis | 1, 6 |
| ⭐⭐⭐ | RAG end to end, chunking, metadata filtering | 2, 3 |
| ⭐⭐⭐ | Embeddings, hybrid search, retrieval metrics | 3 |
| ⭐⭐⭐ | Structured outputs, tool use / function calling | 4 |
| ⭐⭐⭐ | Hallucination reduction, grounding, citations, refusal | 5 |
| ⭐⭐ Strong signal | Reranking, query planning, agents | 7 |
| ⭐⭐ | Tracing, cost/latency optimization, caching, model routing | 7 |
| ⭐⭐ | Evals in CI | 7 |
| ⭐⭐ | Prompt injection / guardrails | 8 |
| ⭐ Nice to have | Job queues, auth, AWS, load testing | 8 |

If you only ever finish through Phase 6, you've covered every ⭐⭐⭐ item. That's why v1 is the point where you start applying.

---

## Habits for every phase

- **Change one thing at a time**, rerun the eval, write the result in `CHANGELOG.md`.
- **Keep a "hardest bugs" note** as things break. You'll forget the details otherwise, and they're your best interview stories.
- **Only put numbers on your resume that you measured** and can reproduce.
- **Timebox parsing.** Use existing libraries; only go custom where the evals prove you need to.
- **Watch API cost.** Iterate on the dev set (or a small slice of it), cache aggressively, and run the full set only when needed.
- **Understand before moving on.** At the end of each phase, explain that phase's "What you'll learn" list out loud in your own words. If you can't, that's the gap to close before continuing.

---

## Glossary (plain-English)

| Term | Meaning |
|---|---|
| **LLM** | Large Language Model, the AI that reads and writes text (GPT, Claude, etc.). |
| **Token** | A word-piece. Models read, write and charge by tokens. |
| **Context window** | How much text the model can see at once. |
| **Prompt / system prompt** | The text you send the model; the system prompt sets its role and rules. |
| **Temperature** | How random the model's output is (0 = most consistent). Some newer models, including Claude Haiku 5.5, don't let you change it. |
| **Effort** | How much the model reasons before answering (low → high). More effort means more tokens, so more cost and time. |
| **RAG** | Retrieval-Augmented Generation: find relevant text first, then have the LLM answer using it. |
| **Chunk** | A small piece of a document that gets stored and searched. |
| **Embedding** | A list of numbers representing a piece of text's meaning; similar meanings get similar numbers. |
| **Vector search / semantic search** | Finding chunks whose embeddings are closest to the question's embedding. |
| **BM25 / keyword search** | Classic search that matches exact words. |
| **Hybrid search** | Using keyword and vector search together and merging the results. |
| **Metadata filter** | Restricting the search to e.g. "Nike, 2023, 10-K, Item 8" before searching. |
| **Reranker** | A second model that carefully reorders search results by relevance. |
| **recall@k** | Share of questions where the right page was in the top *k* results. |
| **Eval / golden set** | A fixed set of questions with known answers used to score the system. |
| **Dev / test set** | Dev is for debugging and tuning; test is held back for honest final numbers. |
| **Baseline** | A simple system you compare against to prove yours is better. |
| **LLM-as-judge** | Using an LLM to grade another LLM's answers against a rubric. |
| **Ablation** | Removing one component at a time to measure how much it contributes. |
| **Structured output** | Making the LLM return data in a fixed format (JSON) instead of free text. |
| **Pydantic** | A Python library for defining data shapes and checking data against them. |
| **Tool use / function calling** | The LLM asks your code to run a function (like the calculator) and uses the result. |
| **Agent** | An LLM that plans steps and calls tools in a loop to finish a task. |
| **Grounding** | Making sure answers come only from provided evidence. |
| **Hallucination** | The model stating something false with confidence. |
| **Citation verification** | Checking that the cited source actually supports the claim. |
| **Refusal calibration** | Refusing when the answer isn't there, but not refusing when it is. |
| **Tracing / observability** | Recording what each step did, how long it took, and what it cost. |
| **Model routing** | Sending easy tasks to a cheap model and hard ones to a strong model. |
| **Prompt injection** | Hidden instructions in input text that try to hijack the model. |
| **XBRL** | The SEC's machine-readable tagged version of a company's financial numbers. |
| **10-K / 10-Q** | A company's annual / quarterly report filed with the SEC. |
| **EDGAR** | The SEC's public database of filings. |
| **Idempotent** | Running something twice gives the same result as running it once (no duplicates). |
| **SSE (Server-Sent Events)** | A way to stream the answer to the browser piece by piece. |
| **CI** | Continuous Integration: automatic checks that run on every code change. |
| **p95 latency** | 95% of requests finish faster than this time. |
