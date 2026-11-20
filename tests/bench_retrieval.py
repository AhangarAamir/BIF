"""Retrieval benchmark: BIF hybrid search vs aamir-rag's search_context.

A case passes at rank k when one of the top k passages comes from the right
file AND contains the marker text that answers the question.

    DATA_DIR=... CORPUS_DIR=... uv run python tests/bench_retrieval.py [--aamir ../aamir-rag]

The corpus is tests/fixtures/build_corpus.py output. It is synthetic and
small, so treat the numbers as a regression check, not a general claim.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

CASES = [
    # question, keyword query (what an agent would send), target file, marker, document hint, folder hint
    ("What does Article 10.7 of the KGD6 PSC state?", "Article 10.7 KGD6 PSC", "KG-DWN-98_3 PSC", "two hundred (200) days", "KGD6 PSC", "PSC"),
    ("What does clause 10.7 of the NEC-OSN-97/2 JOA say?", "10.7 NEC-OSN-97/2 JOA", "NEC-OSN-97-2 JOA", "Sole Risk Development", "NEC-OSN-97/2 JOA", "JOA"),
    ("Definition of discovery area as per KG-D6 PSC", "Discovery Area means", "KG-DWN-98_3 PSC", "likely to be produced in commercial quantities", "KG-D6 PSC", "PSC"),
    ("what is reserviou in KGD6 PSC", "Reservoir definition", "KG-DWN-98_3 PSC", "naturally occurring discrete accumulation", "KGD6 PSC", "PSC"),
    ("Does failing 10.7 affect the right of retention under 21.5?", "21.5 right of retention", "KG-DWN-98_3 PSC", "Right of retention", "", "PSC"),
    ("What is the participating interest of RIL?", "participating interest Reliance", "KG-DWN-98_3 PSC", "ninety per cent (90%)", "", ""),
    ("What is the royalty rate after Amendment No. 1?", "royalty amendment 16.2", "Amendment No 1", "twelve and one half per cent", "", "PSC"),
    ("moping approval of assignment to NBP", "MoPNG approval assignment NBP", "DGH approval assignment", "with effect from 1 August 2018", "", "DGH"),
    ("Government share of profit petroleum if IM is 2.7", "Investment Multiple profit petroleum Government share", "KG-DWN-98_3 PSC", "Government 40%", "", "PSC"),
    ("How long does the contractor have to submit a development plan after commerciality is declared?", "development plan commercial discovery days", "KG-DWN-98_3 PSC", "two hundred (200) days", "", ""),
    ("Can a company transfer its interest without government consent?", "assign participating interest consent Government", "KG-DWN-98_3 PSC", "prior written consent of the Government", "", ""),
    ("What did the management committee note about royalty in the 2019 meeting?", "management committee minutes royalty", "MCM minutes", "pending clarification", "", ""),
    ("When must a discovery be notified to the government?", "Discovery notify Management Committee", "KG-DWN-98_3 PSC", "within thirty", "", "PSC"),
    ("How long after notifying a discovery is the appraisal programme due?", "Appraisal Programme days notification Discovery", "KG-DWN-98_3 PSC", "one hundred and eighty", "", "PSC"),
    ("What does the JOA say about a right of first refusal on transfer?", "right of first refusal transfer", "NEC-OSN-97-2 JOA", "right of first refusal", "NEC-OSN-97/2 JOA", "JOA"),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").lower()


def rank_of(hits: list[dict], target: str, marker: str) -> int:
    for i, hit in enumerate(hits, start=1):
        if target.lower() in (hit.get("file") or "").lower() and _norm(marker) in _norm(hit.get("text")):
            return i
    return 0


def bif_run(query: str, document: str) -> list[dict]:
    from bif.index.search import search

    result = search(query, document=document, top_k=8)
    return [{"file": h["filename"], "text": h["text"]} for h in result["hits"]]


AAMIR_SCRIPT = r"""
import json, sys
from pathlib import Path
from legal_rag.tools.pdf_shell import search_corpus
root = Path(sys.argv[1]); jobs = json.loads(sys.stdin.read()); out = []
for q, folder, filename in jobs:
    r = search_corpus(q, root=root, folder=folder, filename=filename, max_hits=8)
    out.append([{"file": h["filename"], "text": h["snippet"]} for h in r["hits"]])
print(json.dumps(out))
"""


def aamir_run(aamir: Path, corpus: Path, jobs: list[tuple[str, str, str]]) -> list[list[dict]]:
    proc = subprocess.run(
        [str(aamir / ".venv/bin/python"), "-c", AAMIR_SCRIPT, str(corpus)],
        input=json.dumps(jobs), capture_output=True, text=True, cwd=str(aamir), check=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def summarize(name: str, ranks: list[int]) -> str:
    n = len(ranks)
    at1 = sum(1 for r in ranks if r == 1) / n
    at3 = sum(1 for r in ranks if 1 <= r <= 3) / n
    mrr = sum(1 / r for r in ranks if r) / n
    return f"{name:<44} hit@1 {at1:5.0%}   hit@3 {at3:5.0%}   MRR {mrr:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aamir", default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    from bif.config import CORPUS_DIR

    results: dict[str, list[int]] = {}
    modes = [
        ("question, no hints", lambda c: (c[0], "")),
        ("question, document hint", lambda c: (c[0], c[4])),
        ("keywords, no hints", lambda c: (c[1], "")),
        ("keywords, document hint", lambda c: (c[1], c[4])),
    ]
    for label, pick in modes:
        ranks = []
        for case in CASES:
            query, doc = pick(case)
            r = rank_of(bif_run(query, doc), case[2], case[3])
            ranks.append(r)
            if args.verbose and r != 1:
                print(f"  BIF [{label}] rank={r}: {query}")
        results[f"BIF  · {label}"] = ranks

    if args.aamir:
        aamir = Path(args.aamir).resolve()
        for label, use_q, hinted in [
            ("question, no hints", 0, False),
            ("question, folder+file hints", 0, True),
            ("keywords, no hints", 1, False),
            ("keywords, folder+file hints", 1, True),
        ]:
            jobs = [
                (c[use_q], c[5] if hinted else "", "" ) for c in CASES
            ]
            outs = aamir_run(aamir, CORPUS_DIR, jobs)
            ranks = [rank_of(o, c[2], c[3]) for o, c in zip(outs, CASES)]
            if args.verbose:
                for r, c, j in zip(ranks, CASES, jobs):
                    if r != 1:
                        print(f"  aamir [{label}] rank={r}: {j[0]}")
            results[f"aamir-rag · {label}"] = ranks

    print(f"\n{len(CASES)} questions\n")
    for name, ranks in results.items():
        print(summarize(name, ranks))


if __name__ == "__main__":
    main()
