"""Numbers computed from the judge's fact lists and from the agent run. No LLM calls."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

_TOKEN = re.compile(r"[a-z0-9]+")
_VERDICTS = ("correct", "partially_correct", "incorrect", "not_answered")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def token_f1(expected: str, generated: str) -> float:
    """Word-overlap F1 between the expected answer and the generated answer."""
    exp = tokens(expected)
    gen = tokens(generated)
    if not exp and not gen:
        return 1.0
    if not exp or not gen:
        return 0.0
    overlap = sum((Counter(exp) & Counter(gen)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(gen)
    recall = overlap / len(exp)
    return round(2 * precision * recall / (precision + recall), 4)


def fact_recall(covered: list[str], expected: list[str]) -> Optional[float]:
    """covered / expected facts. None when the judge listed no expected facts."""
    if not expected:
        return None
    return round(min(1.0, len(covered) / len(expected)), 4)


def source_hit(doc_id: Optional[int], answer: str, enabled: bool) -> Optional[bool]:
    """True when any cited chunk belongs to the expected source document.

    None when there is no agent run, or the document is not indexed.
    False when the run cited nothing, or cited only other documents.
    """
    if not enabled or doc_id is None:
        return None
    from bif.agent.verify import cited_ids
    from bif.index.search import get_chunks

    ids = cited_ids(answer or "")
    if not ids:
        return False
    return any(chunk["doc_id"] == doc_id for chunk in get_chunks(ids))


def run_stats(run_output: Any) -> dict[str, Any]:
    """Latency, tokens, tool calls and citation checks. All None without a run."""
    empty: dict[str, Any] = {
        "latency_s": None,
        "tool_calls": None,
        "tokens": None,
        "cited": None,
        "unknown_citations": None,
        "unverified_quotes": None,
    }
    if run_output is None:
        return empty
    metrics = getattr(run_output, "metrics", None)
    duration = getattr(metrics, "duration", None) if metrics is not None else None
    tokens_used = getattr(metrics, "total_tokens", None) if metrics is not None else None
    verification = (getattr(run_output, "metadata", None) or {}).get("verification") or {}
    cited = verification.get("cited")
    if cited is None:
        from bif.agent.verify import cited_ids

        content = getattr(run_output, "content", "")
        cited = cited_ids(content if isinstance(content, str) else "")
    return {
        "latency_s": round(float(duration), 3) if isinstance(duration, (int, float)) else None,
        "tool_calls": len(getattr(run_output, "tools", None) or []),
        "tokens": int(tokens_used) if isinstance(tokens_used, (int, float)) else None,
        "cited": list(cited),
        "unknown_citations": list(verification["unknown"]) if "unknown" in verification else None,
        "unverified_quotes": list(verification["unverified_quotes"]) if "unverified_quotes" in verification else None,
    }


def _numbers(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]


def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _pct(count: int, total: int) -> Optional[float]:
    if not total:
        return None
    return round(100.0 * count / total, 1)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll one run's rows into the counts and rates written to summary.json."""
    errors = [row for row in results if row.get("error")]
    evaluated = [row for row in results if not row.get("error") and row.get("verdict") in _VERDICTS]
    count = len(evaluated)

    def n(verdict: str) -> int:
        return sum(1 for row in evaluated if row.get("verdict") == verdict)

    correct, partial = n("correct"), n("partially_correct")
    incorrect, unanswered = n("incorrect"), n("not_answered")
    source_values = [row["source_hit"] for row in evaluated if isinstance(row.get("source_hit"), bool)]
    hallucinated = sum(1 for row in evaluated if row.get("unsupported_claims"))
    citation_issues = 0
    for row in evaluated:
        for key in ("unknown_citations", "unverified_quotes"):
            value = row.get(key)
            if isinstance(value, list):
                citation_issues += len(value)
    return {
        "total": len(results),
        "evaluated": count,
        "errors": len(errors),
        "correct": correct,
        "partially_correct": partial,
        "incorrect": incorrect,
        "not_answered": unanswered,
        "correct_pct": _pct(correct, count),
        "partially_correct_pct": _pct(partial, count),
        "incorrect_pct": _pct(incorrect, count),
        "not_answered_pct": _pct(unanswered, count),
        "accuracy": round(correct / count, 4) if count else None,
        "lenient_accuracy": round((correct + 0.5 * partial) / count, 4) if count else None,
        "average_score": _mean(_numbers(evaluated, "score")),
        "average_fact_recall": _mean(_numbers(evaluated, "fact_recall")),
        "average_f1": _mean(_numbers(evaluated, "token_f1")),
        "source_hit_rate": round(sum(1 for hit in source_values if hit) / len(source_values), 4) if source_values else None,
        "hallucination_rate": round(hallucinated / count, 4) if count else None,
        "citation_issues": citation_issues,
        "average_latency_s": _mean(_numbers(evaluated, "latency_s")),
    }


def format_summary(summary: dict[str, Any]) -> str:
    """One line for the terminal, e.g. Correct 11/15 (73.3%) | Avg score 7.8/10 | ..."""
    evaluated = summary.get("evaluated") or 0
    correct = summary.get("correct") or 0
    correct_pct = summary.get("correct_pct")
    pct = "n/a" if not isinstance(correct_pct, (int, float)) else f"{correct_pct:.1f}%"
    score = summary.get("average_score")
    score_text = "n/a" if not isinstance(score, (int, float)) else f"{score:.1f}/10"
    recall = summary.get("average_fact_recall")
    recall_text = "n/a" if not isinstance(recall, (int, float)) else f"{recall * 100:.0f}%"
    hit = summary.get("source_hit_rate")
    hit_text = "n/a" if not isinstance(hit, (int, float)) else f"{hit * 100:.0f}%"
    line = f"Correct {correct}/{evaluated} ({pct}) | Avg score {score_text} | Fact recall {recall_text} | Source hit {hit_text}"
    if summary.get("errors"):
        line += f" | errors {summary['errors']}"
    return line
