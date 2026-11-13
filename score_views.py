#!/usr/bin/env python3
"""Scores that count a wrong answer as worse than a blank, read from the graded cells.

Accuracy (correct / answerable) scores a blank the same as a wrong answer. The task text told every agent that a wrong
answer counts against it more than an unknown. This script reports the three outcomes separately and one score that
keeps that promise:

  right  = a correct answer, or an honest unknown on a fact the truth set calls unfindable
  wrong  = a wrong answer, or any answer asserted on an unfindable fact
  blank  = an unknown on a fact that was knowable
  net(p) = 100 * (right - p * wrong) / graded cells      p = what a wrong answer costs, in blanks

net(0) ranks by right answers alone; net(1) is the headline; the sweep shows where rankings cross.
Changes nothing it reads. Bootstrap over companies, 2000 resamples, seed 20261108.
grade.py imports views() for its report headline; the arithmetic lives here only.

The withdrawn fact (eval_common.WITHDRAWN_FIELDS) is left out; --all-facts includes it and writes to
grading/score_views_all_facts.

  python3 score_views.py [--grading grading] [--out grading/score_views] [--all-facts]
"""
from __future__ import annotations

import argparse
import collections
import csv
import os
import random

import eval_common as ec

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "grading", "score_views")
PENALTIES = [0, 0.5, 1, 1.5, 2, 3]
# paired differences on the net score: each step up within a vendor, Exa's and Parallel's lowest setting against
# their highest, and Clay Argon against Parallel pro
PAIRS = [("exa-agent-medium-A-v1", "exa-agent-xhigh-v1"), ("exa-agent-medium-A-v1", "exa-agent-high-B-v1"),
         ("exa-agent-high-B-v1", "exa-agent-xhigh-v1"),
         ("claygent-auto-A-v1", "claygent-argon-B-v1"), ("claygent-luna-v1", "claygent-auto-A-v1"),
         ("parallel-core-A-v1", "parallel-pro-B-v1"), ("parallel-core-A-v1", "parallel-ultra-C-v1"),
         ("parallel-pro-B-v1", "parallel-ultra-C-v1"),
         ("claygent-argon-B-v1", "parallel-pro-B-v1")]
ORDER = ["exa-agent-medium-A-v1", "exa-agent-high-B-v1", "exa-agent-xhigh-v1", "claygent-luna-v1", "claygent-auto-A-v1",
         "claygent-argon-B-v1", "parallel-core-A-v1", "parallel-pro-B-v1", "parallel-ultra-C-v1"]

csv.field_size_limit(10**9)


def views(cells, pairs=None, seed: int = 20261108, resamples: int = 2000):
    """cells: rows with config_id, domain, grade (correct | wrong | unknown; anything else is skipped).
    Returns {configs, rows, ranks, pairs, net} where net(cfg, doms, p) is the net score on those companies."""
    pairs = PAIRS if pairs is None else pairs
    per = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0]))
    for r in cells:
        i = {"correct": 0, "wrong": 1, "unknown": 2}.get(r["grade"])
        if i is None:
            continue
        per[r["config_id"]][r["domain"]][i] += 1
    configs = [c for c in ORDER if c in per] + sorted(c for c in per if c not in ORDER)
    companies = sorted({d for c in per for d in per[c]})

    def totals(cfg, doms):
        R = W = B = 0
        for d in doms:
            r, w, b = per[cfg][d]
            R += r; W += w; B += b
        return R, W, B

    def net(cfg, doms, p):
        R, W, B = totals(cfg, doms)
        n = R + W + B
        return 100 * (R - p * W) / n if n else 0.0

    rng = random.Random(seed)
    samples = [[rng.choice(companies) for _ in companies] for _ in range(resamples)]
    lo_i, hi_i = int(round(0.025 * resamples)) - 1, int(round(0.975 * resamples)) - 1

    def ci(fn):
        xs = sorted(fn(s) for s in samples)
        return xs[lo_i], xs[hi_i]

    rows = []
    for c in configs:
        R, W, B = totals(c, companies)
        n = R + W + B
        lo, hi = ci(lambda s, c=c: net(c, s, 1))
        row = {"config": c, "graded": n, "right_per_100": round(100 * R / n, 1), "wrong_per_100": round(100 * W / n, 1),
               "blank_per_100": round(100 * B / n, 1), "net_1": round(net(c, companies, 1), 1),
               "net_1_lo": round(lo, 1), "net_1_hi": round(hi, 1)}
        for p in PENALTIES:
            row[f"net_{p}"] = round(net(c, companies, p), 1)
        rows.append(row)
    ranks = {p: [(c, round(net(c, companies, p), 1)) for c in sorted(configs, key=lambda c: -net(c, companies, p))] for p in PENALTIES}
    paired = []
    for x, y in pairs:
        if x in per and y in per:
            d = net(y, companies, 1) - net(x, companies, 1)
            lo, hi = ci(lambda s, x=x, y=y: net(y, s, 1) - net(x, s, 1))
            paired.append({"first": x, "second": y, "diff_net_1": round(d, 1), "lo": round(lo, 1), "hi": round(hi, 1),
                           "clear_of_zero": bool(lo > 0 or hi < 0), "_d": d, "_lo": lo, "_hi": hi})
    return {"configs": configs, "rows": rows, "ranks": ranks, "pairs": paired, "net": net, "companies": companies}


def summary_lines(v, title: str):
    lines = [title, "",
             "Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.", "",
             "| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in v["rows"]:
        lines.append(f"| {r['config']} | {r['right_per_100']} | {r['wrong_per_100']} | {r['blank_per_100']} | **{r['net_1']}** | "
                     f"{r['net_1_lo']} to {r['net_1_hi']} | {r['net_0']} | {r['net_2']} | {r['net_3']} |")
    lines += ["", "## Rank at each cost of a wrong answer", "", "| wrong costs | order, best first |", "|---|---|"]
    for p in PENALTIES:
        lines.append(f"| {p} | " + ", ".join(f"{c} ({n:.1f})" for c, n in v["ranks"][p]) + " |")
    lines += ["", "## Paired differences on the net score (wrong costs 1), second minus first", "",
              "| first | second | difference | 95% interval | clear of zero |", "|---|---|---|---|---|"]
    for q in v["pairs"]:
        lines.append(f"| {q['first']} | {q['second']} | {q['_d']:+.1f} | {q['_lo']:+.1f} to {q['_hi']:+.1f} | {'yes' if q['clear_of_zero'] else 'no'} |")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grading", default="grading", help="folder holding cells.csv (default grading)")
    ap.add_argument("--out", default=None, help="folder for net_scores.csv and summary.md (default grading/score_views, "
                                                "or grading/score_views_all_facts with --all-facts)")
    ap.add_argument("--all-facts", action="store_true", help="include the withdrawn fact")
    a = ap.parse_args()
    a.out = a.out or (OUT + "_all_facts" if a.all_facts else OUT)
    out = a.out if os.path.isabs(a.out) else os.path.join(HERE, a.out)
    os.makedirs(out, exist_ok=True)
    cells = ec.scored(csv.DictReader(open(os.path.join(HERE, a.grading, "cells.csv"))), a.all_facts)
    facts = len({r["field"] for r in cells})
    cells = [r for r in cells if r["grade"] != "ungraded"]
    v = views(cells)
    rows = v["rows"]
    with open(os.path.join(out, "net_scores.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    text = "\n".join(summary_lines(v, f"# Score views from `{a.grading}`" + (", withdrawn fact included" if a.all_facts else f", {facts} facts"))) + "\n"
    open(os.path.join(out, "summary.md"), "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
