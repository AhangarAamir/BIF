"""Evaluation agent: one structured judgement from the expected answer and source passages."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from agno.agent import Agent
from pydantic import BaseModel, Field, field_validator

from bif.agent.prompts import EVAL_INSTRUCTIONS
from bif.eval.dataset import EvalCase, normalize_path
from bif.index import store
from bif.index.search import get_chunks, search
from bif.models import build_chat_model
from bif.settings import ModelProfile

EVAL_AGENT_ID = "eval-agent"
_PASSAGE_CHARS = 900
_PASSAGE_LIMIT = 6
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class EvalVerdict(BaseModel):
    verdict: Literal["correct", "partially_correct", "incorrect", "not_answered"]
    score: int = Field(ge=0, le=10)
    expected_facts: list[str] = Field(default_factory=list)
    facts_covered: list[str] = Field(default_factory=list)
    facts_missing: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: Any) -> int:
        number = int(round(float(value)))
        return max(0, min(10, number))

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: Any) -> str:
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if text == "partial":
            return "partially_correct"
        return text


def build_eval_agent(profile: Optional[ModelProfile] = None) -> Agent:
    """Build the judge and register it so a model switch updates it too."""
    from bif.agent.agents import _agents

    agent = Agent(
        id=EVAL_AGENT_ID,
        name="Evaluation Agent",
        description="Scores a query-agent answer against an expected answer and source passages.",
        model=build_chat_model(profile),
        instructions=EVAL_INSTRUCTIONS,
        output_schema=EvalVerdict,
        parse_response=True,
        markdown=False,
        add_history_to_context=False,
        add_datetime_to_context=False,
    )
    _agents[EVAL_AGENT_ID] = agent
    return agent


def get_eval_agent() -> Agent:
    from bif.agent.agents import _agents

    agent = _agents.get(EVAL_AGENT_ID)
    if agent is None:
        agent = build_eval_agent()
    return agent


def find_source(source_file: str) -> Optional[dict[str, Any]]:
    return store.find_document_by_path(normalize_path(source_file))


def _format_passages(hits: list[dict[str, Any]]) -> str:
    blocks = []
    for hit in hits:
        where = hit.get("clause_id") or hit.get("article") or hit.get("heading") or ""
        text = (hit.get("text") or "").strip()
        if len(text) > _PASSAGE_CHARS:
            text = text[:_PASSAGE_CHARS] + "…"
        blocks.append(
            f"[C{hit['id']}] {hit.get('document', '')} {where} p.{hit.get('page_start')} ({hit.get('path', '')})\n{text}"
        )
    return "\n\n".join(blocks)


def gather_evidence(doc: dict[str, Any], case: EvalCase, answer: str) -> str:
    """Top passages of the expected file, plus any chunks the answer cited."""
    from bif.agent.verify import cited_ids

    looked = search(case.question, document=doc.get("filename") or "", top_k=_PASSAGE_LIMIT)
    hits = [hit for hit in looked.get("hits") or [] if hit.get("doc_id") == doc["id"]]
    if not hits:
        rows = store.query(
            "SELECT id FROM chunks WHERE doc_id=? ORDER BY ord LIMIT ?",
            (doc["id"], _PASSAGE_LIMIT),
        )
        hits = get_chunks([int(row["id"]) for row in rows])
    seen = {hit["id"] for hit in hits}
    cited = []
    for hit in get_chunks(cited_ids(answer or "")):
        if hit["id"] not in seen:
            cited.append(hit)
            seen.add(hit["id"])
    parts = []
    if hits:
        parts.append("Passages from the expected source file:\n" + _format_passages(hits[:_PASSAGE_LIMIT]))
    if cited:
        parts.append("Other passages the answer cited:\n" + _format_passages(cited))
    return "\n\n".join(parts)


def _as_verdict(content: Any) -> EvalVerdict:
    if isinstance(content, EvalVerdict):
        return content
    if isinstance(content, BaseModel):
        return EvalVerdict.model_validate(content.model_dump())
    if isinstance(content, dict):
        return EvalVerdict.model_validate(content)
    if isinstance(content, str):
        match = _JSON_OBJECT.search(content.strip())
        if not match:
            raise ValueError("Judge did not return JSON.")
        return EvalVerdict.model_validate_json(match.group(0))
    raise TypeError(f"Unexpected judge output: {type(content).__name__}")


def judge_answer(case: EvalCase, answer: str, evidence: str) -> EvalVerdict:
    prompt = (
        f"Question:\n{case.question}\n\n"
        f"Expected answer:\n{case.expected_answer}\n\n"
        f"Source passages:\n{evidence or '(none retrieved)'}\n\n"
        f"Generated answer:\n{answer or '(empty)'}\n"
    )
    result = get_eval_agent().run(prompt)
    return _as_verdict(result.content)
