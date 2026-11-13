#!/usr/bin/env python3
"""Paste-ready config for the Claygent arm (Clay docs read 2026-11-06).

Claygent has no request body to send, so the "client" is what gets pasted into a
Use AI column (Configure tab, Web research). Everything here is generated from
brief_task.py, so the words are the ones every other vendor gets:

  claygent_kit/prompt.txt                 shared task text; [[Name]] and [[Domain]] are the
                                          two places a Clay column chip goes, nothing else
  claygent_kit/output_schema.json         shared vendor schema, for Define outputs > JSON Schema
  claygent_kit/output_schema_strict.json  all-required, no-extra-properties, null-union dialect
                                          (the Parallel rewrite); the fallback if Clay answers
                                          "Unable to parse the output schema"
  claygent_kit/inputs_<csv>.csv           name and domain only, so no answer column from the
                                          pool file (funding_note, band) ever reaches the table
  claygent_kit/inputs_smoke_3.csv         one rich, one medium, one thin company, for a smoke test

Usage:
  python3 claygent_kit.py                       # run date = today, inputs from scored_120.csv
  python3 claygent_kit.py --run-date 2026-11-09 --csv scored_120.csv   # the published kit
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os

import brief_task
from run_parallel_task import parallel_schema

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "claygent_kit")
SMOKE = ["colabsoftware.com", "amplifai.com", "advocate.app"]   # the first rich, medium and thin company in scored_120.csv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", default=datetime.date.today().isoformat())
    ap.add_argument("--csv", default="scored_120.csv", help="company list with name and domain columns")
    ap.add_argument("--prompt-version", default=brief_task.PROMPT_VERSION, choices=brief_task.PROMPT_VERSIONS,
                    help="task text version (brief_task.PROMPT_VERSION)")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    prompt = brief_task.task_prompt("[[Name]]", "[[Domain]]", a.run_date, a.prompt_version)
    with open(os.path.join(OUT, "prompt.txt"), "w") as f:
        f.write(prompt + "\n")
    with open(os.path.join(OUT, "output_schema.json"), "w") as f:
        json.dump(brief_task.vendor_schema(a.prompt_version), f, indent=2)
    with open(os.path.join(OUT, "output_schema_strict.json"), "w") as f:
        json.dump(parallel_schema(), f, indent=2)

    rows = list(csv.DictReader(open(os.path.join(HERE, a.csv))))
    stem = os.path.splitext(os.path.basename(a.csv))[0]
    for name, keep in ((f"inputs_{stem}.csv", rows),
                       ("inputs_smoke_3.csv", [r for d in SMOKE for r in rows if r["domain"] == d])):
        with open(os.path.join(OUT, name), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Name", "Domain"])
            w.writerows([r["name"], r["domain"]] for r in keep)

    print(f"prompt version {a.prompt_version}, run date {a.run_date}")
    print(f"prompt.txt: {len(prompt)} chars, {len(prompt.split())} words")
    print(f"output_schema.json: {len(json.dumps(brief_task.vendor_schema(a.prompt_version)))} chars; "
          f"strict: {len(json.dumps(parallel_schema()))} chars")
    print(f"inputs_{stem}.csv: {len(rows)} rows; inputs_smoke_3.csv: 3 rows -> {OUT}")


if __name__ == "__main__":
    main()
