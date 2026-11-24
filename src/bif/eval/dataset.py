"""Golden cases: question, expected answer, and the indexed source file."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

from bif.config import EVAL_DATASET

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")

_cache: dict[str, tuple[tuple[int, int], dict[str, "EvalCase"]]] = {}


class EvalCase(BaseModel):
    id: str
    question: str
    expected_answer: str
    source_file: str

    model_config = {"extra": "ignore"}


def normalize_question(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace. Used for live matching."""
    text = _PUNCT.sub(" ", (text or "").lower())
    return _SPACE.sub(" ", text).strip()


def normalize_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip().lstrip("/")


def load_cases(path: str | Path) -> list[EvalCase]:
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{file} is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ValueError(f"{file} must be a JSON list of cases.")
    cases: list[EvalCase] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Case {index} in {file} is not an object.")
        if not str(item.get("id") or "").strip():
            item = {**item, "id": f"q{index}"}
        try:
            cases.append(EvalCase.model_validate(item))
        except ValidationError as exc:
            raise ValueError(f"Case {index} in {file} is invalid: {exc}") from exc
    return cases


def _index(path: Path) -> dict[str, EvalCase]:
    stat = path.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    index: dict[str, EvalCase] = {}
    for case in load_cases(path):
        index.setdefault(normalize_question(case.question), case)
    _cache[str(path)] = (key, index)
    return index


def find_case(question: str, path: Path | None = None) -> EvalCase | None:
    """Exact match against the golden file. No fuzzy match."""
    file = path or EVAL_DATASET
    if not file.is_file():
        return None
    return _index(file).get(normalize_question(question))


def reset_cache() -> None:
    _cache.clear()
