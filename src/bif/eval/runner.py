"""One scoring path for live chat and a batch of fresh agent runs."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agno.agent import Agent
from agno.hooks import hook
from agno.run.agent import RunOutput

from bif.agent.verify import VERIFY_MARK, _strip_reference_section
from bif.config import EVAL_LIVE
from bif.eval.dataset import EvalCase, find_case, load_cases, normalize_path
from bif.eval.judge import find_source, gather_evidence, judge_answer
from bif.eval.metrics import fact_recall, run_stats, source_hit, token_f1
from bif.eval.report import append_result, read_summary
from bif.index import store
from bif.settings import active_profile

log = logging.getLogger("bif.eval")

_THINK = re.compile(r"(?s)<think>.*?</think>\s*")
_VERIFY_NOTE = re.compile(r"(?m)^> \*\*Verification:\*\*.*$")


def answer_body(text: str) -> str:
    """Drop the auto-added references and verification note before scoring."""
    text = _THINK.sub("", text or "")
    text = text.replace(VERIFY_MARK, "")
    text = _strip_reference_section(text)
    return _VERIFY_NOTE.sub("", text).strip()


def question_of(run_output: RunOutput) -> str:
    run_input = getattr(run_output, "input", None)
    raw = getattr(run_input, "input_content", None) if run_input is not None else None
    if isinstance(raw, str):
        return raw
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(raw, dict):
        value = raw.get("content") or raw.get("input") or ""
        return value if isinstance(value, str) else ""
    if isinstance(raw, list):
        for item in reversed(raw):
            if isinstance(item, str) and item.strip():
                return item
            content = getattr(item, "content", None)
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(case: EvalCase, answer: str, run_output: Optional[RunOutput], tag: str) -> dict[str, Any]:
    model = ""
    run_id = None
    if run_output is not None:
        model = str(getattr(run_output, "model", "") or "")
        run_id = getattr(run_output, "run_id", None)
    record: dict[str, Any] = {
        "id": case.id,
        "run_tag": tag,
        "run_id": run_id,
        "timestamp": _now(),
        "model": model,
        "judge_model": "",
        "question": case.question,
        "expected_answer": case.expected_answer,
        "source_file": case.source_file,
        "generated_answer": answer,
        "error": None,
        "verdict": None,
        "score": None,
        "reason": "",
        "expected_facts": [],
        "facts_covered": [],
        "facts_missing": [],
        "unsupported_claims": [],
        "fact_recall": None,
        "token_f1": None,
        "source_hit": None,
        "cited": None,
        "unknown_citations": None,
        "unverified_quotes": None,
        "latency_s": None,
        "tool_calls": None,
        "tokens": None,
    }
    record.update(run_stats(run_output))
    return record


def error_record(case: EvalCase, tag: str, error: str, answer: str = "") -> dict[str, Any]:
    record = _record(case, answer, None, tag)
    record["error"] = error
    return record


def evaluate_case(
    case: EvalCase,
    answer: str,
    run_output: Optional[RunOutput] = None,
    tag: str = "live",
) -> dict[str, Any]:
    """Score one answer and append the row. Case-level failures are stored, not raised."""
    cleaned = answer_body(answer)
    record = _record(case, answer, run_output, tag)
    record["token_f1"] = token_f1(case.expected_answer, cleaned)
    doc = find_source(case.source_file)
    if doc is None:
        record["error"] = "source not indexed"
        append_result(record)
        return record
    try:
        evidence = gather_evidence(doc, case, answer)
        verdict = judge_answer(case, cleaned, evidence)
        record["judge_model"] = active_profile().model
        record["verdict"] = verdict.verdict
        record["score"] = verdict.score
        record["reason"] = verdict.reason
        record["expected_facts"] = verdict.expected_facts
        record["facts_covered"] = verdict.facts_covered
        record["facts_missing"] = verdict.facts_missing
        record["unsupported_claims"] = verdict.unsupported_claims
        record["fact_recall"] = fact_recall(verdict.facts_covered, verdict.expected_facts)
        record["source_hit"] = source_hit(doc["id"], answer, run_output is not None)
    except Exception as exc:
        log.exception("evaluation failed for %s", case.id)
        record["error"] = str(exc)
    append_result(record)
    return record


def _case_from_metadata(raw: Any) -> Optional[EvalCase]:
    if isinstance(raw, EvalCase):
        return raw
    if isinstance(raw, dict):
        return EvalCase.model_validate(raw)
    return None


@hook(run_in_background=True)
def evaluate_answer(run_output: RunOutput, agent: Agent) -> None:
    """Post-hook. Background under AgentOS, inline under agent.run() in the CLI.

    A failure here is logged and never raised, so a chat answer is not lost.
    """
    try:
        meta = dict(run_output.metadata or {})
        case = _case_from_metadata(meta.get("eval_case"))
        if case is None and EVAL_LIVE:
            case = find_case(question_of(run_output))
        if case is None:
            return
        tag = str(meta.get("eval_run") or "live")
        content = run_output.content if isinstance(run_output.content, str) else str(run_output.content or "")
        evaluate_case(case, content, run_output, tag=tag)
    except Exception:
        log.exception("evaluation hook failed")


def run_batch(path: str | Path, *, tag: str = "") -> dict[str, Any]:
    """Ask the query agent each question in the file, then score its answer."""
    cases = load_cases(path)
    if not cases:
        raise ValueError(f"No cases in {path}.")
    tag = tag.strip() or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    from bif.agent.agents import build_query_agent
    from bif.eval.judge import build_eval_agent

    build_eval_agent()
    agent = build_query_agent()
    for case in cases:
        if store.find_document_by_path(normalize_path(case.source_file)) is None:
            append_result(error_record(case, tag, "source not indexed"))
            continue
        try:
            agent.run(
                case.question,
                session_id=f"eval-{uuid.uuid4().hex}",
                metadata={"eval_case": case.model_dump(), "eval_run": tag},
            )
        except Exception as exc:
            log.exception("query agent failed for %s", case.id)
            append_result(error_record(case, tag, f"query agent failed: {exc}"))
    return read_summary().get(tag) or {}
