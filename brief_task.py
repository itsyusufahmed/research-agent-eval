#!/usr/bin/env python3
"""Shared task text, vendor-facing output schema and normalizer for every config.

One prompt and one output schema for every vendor and model, so the only thing
that changes between configs is the product or model being graded:

  task_prompt(name, domain, run_date)  -> the research brief, identical everywhere
  vendor_schema()                      -> a flat JSON Schema the vendor fills
  normalize(structured, ...)           -> a record in brief_schema.json's shape
  validate(record)                     -> schema errors (empty list = clean)

Why a flat vendor schema instead of brief_schema.json itself: brief_schema.json
uses $ref and oneOf/const arms, which structured-output engines often reject or
handle unevenly. The flat shape (status, value, citations, notes per field;
value omitted when unknown) is the most portable common denominator, and the
normalizer maps it into brief_schema.json without changing any answer. Anything
the normalizer cannot map cleanly (an asserted answer with no citation, a
malformed date) is left in place so validate() reports it.

The task text (PROMPT_VERSION v1-2026-11-10) asks 17 questions. Each question
whose answer can be negative (false, "none", an empty list) carries a clause
saying when the answer is negative and which page to cite for it, the same
definition the grader applies (grading_rules.md). The rules state the scoring:
a correct answer scores one, an unknown zero, a wrong answer below zero.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_VERSION = "v1-2026-11-10"           # every client records it in the manifest and in each record
PROMPT_VERSIONS = (PROMPT_VERSION,)

BANDS = ["11-20", "21-50", "51-100", "101-200", "201-500"]

# field_id -> (value kind, question text), in the order the agent sees them.
# Other modules destructure the tuples as (fid, kind, q).
FIELDS: List[tuple] = [
    ("product_one_liner", "string",
     "What does the product do, and who is it for? One sentence."),
    ("pricing_page", "bool",
     "Does the company have a public pricing page? If true, cite the pricing page."),
    ("named_customers", "list",
     "Name at least two of its customers. Every name must appear on a cited page "
     "(logo wall, case study, review)."),
    ("employee_band", "band",
     "Employee count band: exactly one of 11-20, 21-50, 51-100, 101-200, 201-500."),
    ("hq_location", "location", "Headquarters city and country."),
    ("founded_year", "year", "Year founded."),
    ("eng_blog", "bool",
     "Does the company have an engineering or technical blog (not the marketing blog)?"),
    ("public_docs", "bool",
     "Does it have public product documentation or a developer portal?"),
    ("ai_ml_roles_open", "bool",
     "Does it have an open AI, ML or data-science role right now? If true, cite a live posting."),
    ("model_provider", "string",
     "Which AI model or model provider does the product publicly say it uses? "
     "Unknown if the company has not said so publicly."),
    ("compliance_certs", "list",
     "Which compliance certifications does it publicly claim (SOC 2, ISO 27001, HIPAA, "
     "GDPR, PCI DSS)? List only certifications named on the cited page."),
    ("last_funding", "funding",
     "Its most recent funding round: stage, date (YYYY-MM) and amount in USD. "
     "If the company has no known outside funding, set stage to \"none\"."),
    ("raised_18mo", "bool",
     "Did it raise funding in the 18 months before {run_date}? Cite a dated announcement or filing."),
    ("hiring_sdr_ae", "bool",
     "Is it hiring SDRs, BDRs or account executives right now? If true, cite a live posting."),
    ("launched_6mo", "bool",
     "Did it launch a product or major feature in the 6 months before {run_date}? "
     "Cite a dated announcement (blog, press release, changelog, LinkedIn)."),
    ("leadership_change_12mo", "bool",
     "Did a C-level or VP-level person join or leave in the 12 months before {run_date}? "
     "Cite a dated announcement or profile."),
    ("crm_stack_signal", "list",
     "Which CRM or sales and marketing systems does it visibly use (job posts, docs, "
     "integration pages)? Each named system must appear on the cited page."),
]
FIELD_IDS = [f[0] for f in FIELDS]

# One clause per question whose answer can be negative, saying when the answer is negative
# and which page to cite. It is the definition the grader applies (the field table in
# grading_rules.md), so the agent and the grader read the same rule. Fields with no
# negative answer (one-liner, band, HQ, year) get no clause; model_provider gets the
# places to look before answering unknown.
NEGATIVE_CLAUSE: Dict[str, str] = {
    "pricing_page":
        "False when the site has no pricing link in its navigation or footer and the pricing URL is "
        "missing or a bare contact form; cite the homepage or that contact page. A pricing page that "
        "lists plans without prices is still true.",
    "named_customers":
        "An empty list when a customers page, case studies or a G2 or Capterra listing exist and show "
        "fewer than two customer names; cite the page that came closest. Partners and investors do not "
        "count as customers.",
    "eng_blog":
        "True needs at least two posts about how the product is built (architecture, infrastructure, ML, "
        "data, incidents, open source), by engineers. False when the blog index shows only product, "
        "marketing or hiring posts, a changelog, release notes, or a single lone engineering post; cite "
        "the blog index. Unknown only when there is no blog at all.",
    "public_docs":
        "True needs a public docs site, help center or developer portal with several articles. False when "
        "no docs or help link exists in the navigation or footer, docs and help subdomains do not resolve, "
        "or only a single FAQ page exists; cite the homepage.",
    "ai_ml_roles_open":
        "False when the careers page or job board is open and lists roles but none has AI, ML, machine "
        "learning, data science, applied scientist, research scientist, NLP, LLM or computer vision in its "
        "title, or the careers page says there are no openings; cite the careers page. Data engineer, "
        "analytics engineer, data analyst, BI and AI-sales titles do not count. Unknown only when no "
        "careers page or job board exists anywhere.",
    "model_provider":
        "Look in the product docs, the AI or security FAQ, the blog and the subprocessor list on the trust "
        "or privacy page before answering unknown.",
    "compliance_certs":
        "An empty list when a security, trust or legal page or a footer badge area exists and names none of "
        "the five; cite that page. A certification described as in progress does not count.",
    "last_funding":
        "Stage \"none\" when funding databases show no rounds and the company describes itself as "
        "bootstrapped or says nothing about outside funding; cite the database profile or the about page.",
    "raised_18mo":
        "False when the most recent round is dated before the window or the company has no outside "
        "funding; cite the last round's announcement or the page that establishes no funding. Unknown only "
        "if you can find no funding history at all.",
    "hiring_sdr_ae":
        "False when the careers page or job board is open and lists roles but none is titled SDR, BDR, "
        "sales or business development representative, or account executive, or the careers page says there "
        "are no openings; cite the careers page. Account manager, customer success, sales engineer, head or "
        "VP of sales and partnerships titles do not count. Unknown only when no careers page or job board "
        "exists anywhere.",
    "launched_6mo":
        "False when the blog, changelog, press page or LinkedIn company posts are readable and the newest "
        "launch-type item (a release, an \"introducing\" or \"announcing\" post, a Product Hunt launch, a "
        "changelog entry presented as new) is dated before the window; cite that newest item or the blog "
        "index. Bug fixes and UI tweaks are not launches. Unknown only when there is no blog, changelog or "
        "post history to read.",
    "leadership_change_12mo":
        "False when the team page is small enough to check in full and shows no C-level or VP who started "
        "inside the window, and no departure was announced; cite the team page or the LinkedIn People tab. "
        "Unknown when the team page is absent or too large to check and nothing else can be verified.",
    "crm_stack_signal":
        "An empty list when job posts, docs or an integrations page are readable and none names a system; "
        "cite the page you read. Unknown only when there are no job posts, docs or integrations page to read.",
}


def _check_version(version: str) -> str:
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown prompt version {version!r}; known: {PROMPT_VERSIONS}")
    return version


def question_text(fid: str, run_date: str, version: str = PROMPT_VERSION) -> str:
    """The question as the agent sees it: the question, then its negative-answer clause when it has one."""
    _check_version(version)
    q = dict((f[0], f[2]) for f in FIELDS)[fid].format(run_date=run_date)
    clause = NEGATIVE_CLAUSE.get(fid)
    return f"{q} {clause}" if clause else q


def task_prompt(name: str, domain: str, run_date: str, version: str = PROMPT_VERSION) -> str:
    version = _check_version(version)
    lines = [
        f"Research the company {name} ({domain}). Today's date is {run_date}.",
        "Answer the 17 questions below about this company only. If another organization "
        "shares its name, ignore that organization.",
        "",
        "Rules:",
        "- Every answer you assert must carry at least one source URL whose page supports it.",
        "- Scoring: a correct answer scores one, an unknown scores zero, a wrong answer scores below "
        "zero. Look for every fact where it would live. Set status to \"unknown\" and leave value out "
        "only when you have looked there and found nothing to cite either way. Never guess.",
        "- A negative answer (false, \"none\", or an empty list) is an answer, not an unknown. It means "
        "the place where the thing would appear exists and does not show it. Cite that place. Each "
        "question below says when its answer is negative and what to cite for it.",
        f"- Time windows are measured back from {run_date}.",
        "",
        "Questions:",
    ]
    for i, (fid, _kind, _q) in enumerate(FIELDS, 1):
        lines.append(f"{i}. {fid}: {question_text(fid, run_date, version)}")
    lines += ["", "Return the result in the provided output schema."]
    return "\n".join(lines)


def _value_schema(kind: str) -> Dict[str, Any]:
    if kind == "string":
        return {"type": "string"}
    if kind == "bool":
        return {"type": "boolean"}
    if kind == "list":
        return {"type": "array", "items": {"type": "string"}}
    if kind == "band":
        return {"type": "string", "enum": BANDS}
    if kind == "location":
        return {"type": "object",
                "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
                "required": ["city", "country"]}
    if kind == "year":
        return {"type": "integer"}
    if kind == "funding":
        return {"type": "object",
                "properties": {"stage": {"type": "string"},
                               "date": {"type": "string", "description": "YYYY-MM"},
                               "amount_usd": {"type": "number"}},
                "required": ["stage"]}
    raise ValueError(kind)


def vendor_schema(version: str = PROMPT_VERSION) -> Dict[str, Any]:
    """Status, value, citations and notes per field; each field's description is its question text."""
    version = _check_version(version)
    props = {}
    for fid, kind, _q in FIELDS:
        props[fid] = {
            "type": "object",
            "description": question_text(fid, "the run date", version),
            "properties": {
                "status": {"type": "string", "enum": ["asserted", "unknown"]},
                "value": _value_schema(kind),
                "citations": {"type": "array", "items": {"type": "string"},
                              "description": "Source URLs that support the answer; empty when unknown."},
                "notes": {"type": "string"},
            },
            "required": ["status", "citations"],
        }
    return {"type": "object", "properties": props, "required": FIELD_IDS}


def config_suffix(version: str = PROMPT_VERSION) -> str:
    """The prompt version's short name that ends every config id: exa-agent-high-B-v1, parallel-core-flat-v1."""
    version = _check_version(version)
    return "-" + version.split("-")[0]


_NONE_STAGES = {"none", "bootstrapped", "no known funding", "no outside funding", "self-funded"}


def _norm_value(kind: str, v: Any) -> Any:
    if kind == "funding" and isinstance(v, dict):
        stage = str(v.get("stage", "")).strip()
        if stage.lower() in _NONE_STAGES:
            return "none"
        out = {"stage": stage, "date": v.get("date")}
        if isinstance(out["date"], str) and re.match(r"^\d{4}-\d{2}-\d{2}", out["date"]):
            out["date"] = out["date"][:7]
        if "amount_usd" in v:
            out["amount_usd"] = v.get("amount_usd")
        return out
    if kind == "location" and isinstance(v, dict):
        return {"city": v.get("city"), "country": v.get("country")}
    return v


def normalize(structured: Dict[str, Any], *, company: str, domain: str, config_id: str,
              run_date: str, track: str = "managed", cost_usd: float | None = None,
              latency_seconds: float | None = None, prompt_version: str | None = None) -> Dict[str, Any]:
    kinds = {fid: kind for fid, kind, _ in FIELDS}
    answers: Dict[str, Any] = {}
    for fid in FIELD_IDS:
        raw = (structured or {}).get(fid)
        if not isinstance(raw, dict):
            answers[fid] = {"status": "unknown", "value": None, "citations": [],
                            "notes": "normalizer: field missing from vendor output"}
            continue
        status = raw.get("status")
        cites = [c for c in (raw.get("citations") or []) if isinstance(c, str) and c.startswith("http")]
        notes = raw.get("notes")
        if status == "unknown":
            ans = {"status": "unknown", "value": None, "citations": []}
        else:
            # asserted, or an unrecognized status left as-is so validate() flags it
            ans = {"status": status, "value": _norm_value(kinds[fid], raw.get("value")), "citations": cites}
        if isinstance(notes, str) and notes:
            ans["notes"] = notes
        answers[fid] = ans
    rec: Dict[str, Any] = {
        "schema_version": "v0", "company": company, "domain": domain,
        "config_id": config_id, "track": track, "run_date": run_date, "answers": answers,
    }
    if prompt_version is not None:
        rec["prompt_version"] = prompt_version
    if cost_usd is not None:
        rec["cost_usd"] = cost_usd
    if latency_seconds is not None:
        rec["latency_seconds"] = round(latency_seconds, 1)
    return rec


def validate(record: Dict[str, Any]) -> List[str]:
    import jsonschema
    schema = json.load(open(os.path.join(HERE, "brief_schema.json")))
    v = jsonschema.Draft202012Validator(schema)
    errs = []
    for e in v.iter_errors(record):
        path = "/".join(str(p) for p in e.absolute_path)
        errs.append(f"{path}: {e.message[:160]}")
    return errs


def tally(record: Dict[str, Any]) -> Dict[str, int]:
    a = record.get("answers", {})
    asserted = [x for x in a.values() if x.get("status") == "asserted"]
    return {
        "asserted": len(asserted),
        "unknown": sum(1 for x in a.values() if x.get("status") == "unknown"),
        "asserted_no_cite": sum(1 for x in asserted if not x.get("citations")),
    }


if __name__ == "__main__":
    print(task_prompt("Example Co", "example.com", "2026-11-09"))
    print(json.dumps(vendor_schema(), indent=1)[:800], "...")
