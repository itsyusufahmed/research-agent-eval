# research-agent-eval

Benchmark 02 of GTM Open, independent evals for go-to-market, run by Zevenue.

Exa Agent, Parallel Task and Claygent, three settings each, researched the same 120 B2B companies. The board scores 16 questions about each company. Each product ran through its own API with the shared task text and output schema and nothing else attached. Each setting ran each company once.

## Results

| Config | $ per 1,000 companies | Accuracy (95%) | Net, wrong costs 1 (95%) | Right / wrong / blank per 100 | Wrong per 100 asserted | Median seconds |
|---|---|---|---|---|---|---|
| Exa Agent xhigh | $1,000 | 90.7 (89.2 to 92.0) | 82.2 (79.4 to 84.7) | 89.8 / 7.6 / 2.6 | 7.9 | 272 |
| Exa Agent high | $500 | 89.5 (88.0 to 91.1) | 80.4 (77.5 to 83.4) | 88.8 / 8.4 / 2.7 | 8.8 | 240 |
| Parallel Task ultra | $300 | 89.4 (88.2 to 90.7) | 77.9 (75.3 to 80.6) | 88.2 / 10.3 / 1.5 | 10.6 | 316 |
| Parallel Task pro | $100 | 87.5 (85.8 to 89.0) | 75.1 (71.8 to 78.2) | 86.3 / 11.3 / 2.4 | 11.7 | 255 |
| Claygent Argon | $155 | 88.0 (86.5 to 89.5) | 74.8 (71.4 to 77.7) | 86.7 / 11.9 / 1.4 | 12.2 | 310 |
| Parallel Task core | $25 | 88.3 (86.9 to 89.7) | 74.3 (71.2 to 77.2) | 86.6 / 12.4 / 1.0 | 12.6 | 418 |
| Claygent Auto | $94 | 82.5 (80.5 to 84.4) | 70.6 (67.2 to 74.1) | 82.2 / 11.5 / 6.3 | 12.5 | 141 |
| Exa Agent medium | $100 | 83.8 (82.1 to 85.4) | 69.3 (66.0 to 72.5) | 82.9 / 13.5 / 3.6 | 14.2 | 94 |
| Claygent Luna | $19 | 75.0 (72.8 to 77.2) | 60.2 (56.5 to 63.8) | 74.7 / 14.5 / 10.8 | 16.5 | 60 |

Sorted by net score. Accuracy is correct answers over answerable facts. Right / wrong / blank are per 100 graded facts, and the net score is right minus wrong. Intervals are 95% company bootstrap. Cost is per 1,000 companies at list price. The full numbers, with yield, trust and abstention, are in `grading/results.csv`; accuracy by presence band is in `grading/results_by_band.csv` and the deltas between settings in `grading/setting_deltas.csv`.

## Files

| Path | What it is |
|---|---|
| `scored_120.csv` | The 120 companies and their band by public footprint, from eight yes-or-no signals: 24 rich, 56 medium, 40 thin |
| `brief_task.py` | The task text, the output schema each vendor fills, and the normalizer that turns a response into a record |
| `brief_schema.json` | The record schema every config's records follow |
| `run_exa_agent.py`, `run_parallel_task.py`, `run_parallel_flat.py`, `run_claygent.py` | One client per product. `run_parallel_flat.py` is Parallel on the flat schema |
| `claygent_kit.py`, `claygent_kit/` | The Claygent prompt and output schemas pasted into the Clay column, and the input list for the table |
| `claygent_raw_meta.py` | Per-row credits and timing read from the Claygent responses |
| `snapshot.py` | Saves a copy of every cited page |
| `grade.py`, `grading_rules.md` | The LLM judge and the rules text it is given |
| `score_views.py` | Right / wrong / blank and the net score at each cost of a wrong answer |
| `results.py` | The results tables: cost, accuracy and net score per config, accuracy by presence band, and the deltas between settings |
| `eval_common.py`, `.env.example` | Shared helpers; the key names the clients read from the environment |
| `runs/` | One folder per product run: Exa Agent, Parallel Task on the shared schema, and Claygent, which make up the nine board configs, plus Parallel Task on a flat 20-property schema, which is not on the board |
| `grading/cells.csv` | One row per company, field and board config: answer, citations, grade, failure tag, the judge's note |
| `grading/truth.csv` | The truth for each company and field, with its URL, provenance and the judge's reason |
| `grading/truth_pages/` | Saved copies of truth URLs that no board answer cites |
| `grading/judge_pages/` | Pages the judge read from its own store instead of `snapshots/`: LinkedIn page captures and pages fetched at grading time. `index.jsonl` lists each one; the copies that are not withheld sit beside it |
| `grading/flat_spot_check/` | Flat vs nested Parallel: `counts.csv`, how often the two schemas' answers differ; `sample.csv`, two seeded draws of facts where they differ, 10 and then 100; `comparison.csv`, every board and flat answer on those 110 facts, graded by Claude Opus 5.5 with the judge's rules and prompts (run as Claude Code subagents), beside the published grades |
| `withheld_sources.txt` | The sources whose page text is withheld, and how a page is matched to them |
| `grading/results.csv`, `grading/results_by_band.csv`, `grading/setting_deltas.csv`, `grading/score_views/` | The results tables and the net scores, rebuilt from `grading/cells.csv` |
| `grading/results_all_facts.csv`, `grading/score_views_all_facts/` | The same with the withdrawn question included |
| `grading/judge_check/` | `sample_cells.csv`, a seeded random draw of 300 cells the judge did not flag; `comparison.csv`, the judge's and a second model's truth and grades on those cells for each board config; `human_rulings.csv`, the human reviewer's rulings on cells where no two models agreed |

Each run folder holds `manifest.json` (the config as run), `raw/` (vendor responses), `records/` (answers in the record schema), `snapshots/` (a copy of each cited page, named by the SHA-1 of its URL, with `index.jsonl` and the side files from fetching), `state.json` (vendor run ids) and `summary.csv`. The Claygent folder adds `credits/` and `meta/`.

## Rerun

The clients read keys from the environment; `.env.example` lists the names. Each script prints its options with `--help`.

```bash
cp .env.example .env
python3 run_exa_agent.py --help
python3 snapshot.py --help
python3 grade.py --help
```

Rebuild the net scores and the results tables from the shipped grades:

```bash
python3 score_views.py
python3 results.py
```

Add `--all-facts` to either to include the withdrawn question.

## Notes

- Three outcomes per fact: correct, wrong, unknown. A right value is graded wrong when its cited page says something else. It is not graded wrong when the page could not be read and the value is confirmed elsewhere.
- One judge, Claude Opus 5.5, graded every judged cell with every candidate in view; the published grades are its grades.
- The judge read each cited page from its saved copy: whole up to 12,000 characters, longer pages as excerpts with a search of the whole page. Dead, blocked and login-gated pages could not be opened, apart from the LinkedIn captures above.
- Some cited pages embed the site's own credentials: signed S3 image links, map API keys, a sample key in API docs. Those values read REDACTED in the saved copies and in the one vendor response that quoted one; `content_sha256` and `chars` on those copies describe the page as fetched. `snapshot.py` and `grade.py` scrub them at fetch time (`eval_common.scrub_credentials`).
- 67 of the 1,920 scored facts were settled as unfindable; 19 of them were never graded; each config is scored on the other 48, where an honest unknown counts as right.
- Parallel's Task API returns no per-run cost, so the list price per processor is used; failed runs are not billed.
- Two configs within about 3 points are not separable at 120 companies; intervals are about 1.5 points either side pooled and 2 to 4 on one band.

## Changes from the plan

The method was written before the runs. These are the changes made after it, in order, each with when it was made and what it did to the board.

- **A third Claygent setting, GPT 6 Luna** (Nov 9, before any grading). Added beside Auto and Argon. Clay describes Luna as its model for cost-sensitive, high-volume work. It ran after the other Claygent settings, on the same 120 companies with the same task text.
- **A second task text** (Nov 10, before the board's runs). The first run exposed a flaw in our own task text; a second text was written and every config ran again. On the first text the stronger tiers underperformed as a result. The board is the second run.
- **Parallel on a flat schema** (Nov 10, beside the board's runs). Parallel's validator flagged the nested schema as complex, so Parallel also ran on a flat 20-property schema with the same task text. On the flat schema Parallel gave the same answer on about 86% of facts. On a spot check of 110 facts where the answers differed, the nested schema outscored the flat schema (+137 net vs. +104, `grading/flat_spot_check/`). The flat run's answers are in `runs/2026-11-10-v1-flat-parallel/`. All three products were evaluated using the same nested schema.
- **LinkedIn pages captured in a browser** (Nov 10, before the grading pass the board reads from). The judge cannot open LinkedIn: a plain fetch meets the login wall and archived copies were missing, so answers citing only LinkedIn reached it as unreachable. Pages it could not open were captured in a browser and given to it as saved copies, listed in `grading/judge_pages/index.jsonl`; the copies themselves are withheld (`withheld_sources.txt`). An unreachable page is never graded wrong on its own.
- **Checks on the judge** (Nov 11 and 12, after grading). A second model, Claude Sonnet 5.5, re-judged every cell the judge flagged and a random 300 of the rest. A third, Claude Fable 5.1, broke the ties on the flagged cells. A human reviewer ruled on cells where no two models agreed. All three judges are Anthropic models. The checks measure the judge; the published grades are its own (`grading/judge_check/`).
- **The CRM and stack question withdrawn from scoring** (Nov 12, after the results were read). The question was asked and answered; the board scores 16 questions, not 17. It had two flaws, both ours. First, the task text asked an open question, which CRM or sales and marketing systems the company visibly uses, but the grading rules accepted only a closed list of 12 systems that no agent was shown. One system off the list made the whole answer wrong: an answer of Salesforce, Marketo and Mailchimp was graded wrong because Mailchimp is not on the list, though the judge found Salesforce and Marketo supported by the cited page. The judge's note cites the list on 188 of the 384 wrong grades this question drew on the board, a text match on the notes, not a hand count. Second, the question named integration pages as a source, and an integrations page shows what a product connects to, not what the company runs. Withdrawing it raises every row's net score by 2.2 to 3.8 points. The order holds, except that Claygent Auto and Exa Agent medium swap places.
- **The judge re-graded with full pages** (Nov 12 and 13). The judge had read only the first 6,000 characters of each cited page, and vendor and model names in its evidence had been masked. Both were fixed, and every fact they touched was graded again. Every row's net score rose by 0.8 to 3.2 points; the order did not change.

## License

Code is MIT. Results data is CC BY 4.0. Saved page copies and vendor responses belong to their owners and are included for verification only. See `LICENSE`.

Page copies from LinkedIn and paid company-data providers are not redistributed. For those pages the index keeps the URL, fetch time and a SHA-256 of the text that was graded.

If you own a page copied here and want it removed, open an issue.

Maintained by Yusuf Ahmed.
