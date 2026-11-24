"""Append one result per line and rewrite summary.json from the whole file."""

from __future__ import annotations

import json
import threading
from typing import Any

from bif.config import EVAL_DIR
from bif.eval.metrics import summarize

_LOCK = threading.RLock()


def results_path():
    return EVAL_DIR / "results.jsonl"


def summary_path():
    return EVAL_DIR / "summary.json"


def load_results() -> list[dict[str, Any]]:
    path = results_path()
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("run_tag") or ""), []).append(row)
    summary = {}
    for tag, items in grouped.items():
        block = summarize(items)
        block["run_tag"] = tag
        summary[tag] = block
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    summary_path().write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def append_result(record: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        with results_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return _write_summary(load_results())


def read_summary() -> dict[str, Any]:
    path = summary_path()
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
