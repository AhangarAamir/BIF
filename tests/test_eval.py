"""Offline checks for the evaluation agent. No model calls."""

import json
from types import SimpleNamespace

import pytest
from agno.hooks.decorator import should_run_in_background

from bif.agent.agents import build_query_agent
from bif.eval import dataset, report, runner
from bif.eval.dataset import EvalCase, normalize_question
from bif.eval.metrics import fact_recall, format_summary, source_hit, summarize, token_f1


@pytest.fixture(autouse=True)
def clean_eval_files():
    from bif.config import EVAL_DIR

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("results.jsonl", "summary.json"):
        path = EVAL_DIR / name
        if path.exists():
            path.unlink()
    dataset.reset_cache()
    yield


def test_normalize_question_drops_case_and_punctuation():
    assert normalize_question("  What does Article 10.7 say? ") == "what does article 10 7 say"


def test_find_case_is_exact_after_normalizing(tmp_path, monkeypatch):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps([
        {
            "id": "q1",
            "question": "What does Article 10.7 say?",
            "expected_answer": "200 days",
            "source_file": "PSC/a.pdf",
        }
    ]), encoding="utf-8")
    monkeypatch.setattr(dataset, "EVAL_DATASET", path)
    found = dataset.find_case("what does article 10.7 say?")
    assert found is not None and found.id == "q1"
    assert dataset.find_case("tell me about article 10.7") is None


def test_token_f1_and_fact_recall():
    assert token_f1("two hundred days", "two hundred days") == 1.0
    assert token_f1("two hundred days", "ninety days") == 0.4
    assert token_f1("", "") == 1.0
    assert token_f1("days", "") == 0.0
    assert fact_recall(["a", "b"], ["a", "b", "c", "d"]) == 0.5
    assert fact_recall(["a", "b", "c"], ["a"]) == 1.0
    assert fact_recall([], []) is None


def test_source_hit_uses_cited_chunks(monkeypatch):
    monkeypatch.setattr("bif.index.search.get_chunks", lambda ids: [{"id": ids[0], "doc_id": 3}])
    assert source_hit(3, "The period is 200 days [C12].", True) is True
    assert source_hit(9, "The period is 200 days [C12].", True) is False
    assert source_hit(3, "The period is 200 days.", True) is False
    assert source_hit(3, "The period is 200 days [C12].", False) is None


def test_summarize_counts_and_rates():
    rows = [
        {
            "error": None, "verdict": "correct", "score": 10, "fact_recall": 1.0, "token_f1": 1.0,
            "source_hit": True, "unsupported_claims": [], "unknown_citations": [], "unverified_quotes": [],
            "latency_s": 2.0,
        },
        {
            "error": None, "verdict": "partially_correct", "score": 5, "fact_recall": 0.5, "token_f1": 0.4,
            "source_hit": False, "unsupported_claims": ["x"], "unknown_citations": [9], "unverified_quotes": ["q"],
            "latency_s": 4.0,
        },
        {"error": "source not indexed", "verdict": None},
    ]
    summary = summarize(rows)
    assert summary["total"] == 3
    assert summary["evaluated"] == 2
    assert summary["errors"] == 1
    assert summary["correct"] == 1
    assert summary["partially_correct"] == 1
    assert summary["accuracy"] == 0.5
    assert summary["lenient_accuracy"] == 0.75
    assert summary["average_score"] == 7.5
    assert summary["average_fact_recall"] == 0.75
    assert summary["source_hit_rate"] == 0.5
    assert summary["hallucination_rate"] == 0.5
    assert summary["citation_issues"] == 2
    assert summary["average_latency_s"] == 3.0
    assert summary["correct_pct"] == 50.0
    assert format_summary(summary) == (
        "Correct 1/2 (50.0%) | Avg score 7.5/10 | Fact recall 75% | Source hit 50% | errors 1"
    )


def test_query_agent_verifies_before_the_background_eval_hook():
    hooks = build_query_agent().post_hooks
    assert hooks[0].__name__ == "finalize_answer"
    assert hooks[1].__name__ == "evaluate_answer"
    assert should_run_in_background(hooks[1]) is True


def test_hook_skips_when_live_eval_is_off(monkeypatch):
    monkeypatch.setattr(runner, "EVAL_LIVE", False)
    called = []
    monkeypatch.setattr(runner, "evaluate_case", lambda *args, **kwargs: called.append(1))
    output = SimpleNamespace(metadata=None, content="hi", input=SimpleNamespace(input_content="What is the royalty?"))
    runner.evaluate_answer(output, None)
    assert called == []


def test_hook_skips_a_question_that_is_not_in_the_golden_set(monkeypatch):
    monkeypatch.setattr(runner, "EVAL_LIVE", True)
    monkeypatch.setattr(runner, "find_case", lambda question: None)
    called = []
    monkeypatch.setattr(runner, "evaluate_case", lambda *args, **kwargs: called.append(1))
    output = SimpleNamespace(metadata={}, content="hi", input=SimpleNamespace(input_content="not a golden question"))
    runner.evaluate_answer(output, None)
    assert called == []


def test_hook_scores_the_case_passed_in_run_metadata(monkeypatch):
    monkeypatch.setattr(runner, "EVAL_LIVE", False)
    seen = {}

    def fake(case, answer, run_output, tag="live"):
        seen["id"] = case.id
        seen["answer"] = answer
        seen["tag"] = tag
        seen["has_run"] = run_output is not None

    monkeypatch.setattr(runner, "evaluate_case", fake)
    output = SimpleNamespace(
        metadata={
            "eval_case": {"id": "q1", "question": "Q?", "expected_answer": "A", "source_file": "a.pdf"},
            "eval_run": "batch-1",
        },
        content="the answer",
        input=SimpleNamespace(input_content="ignored"),
    )
    runner.evaluate_answer(output, None)
    assert seen == {"id": "q1", "answer": "the answer", "tag": "batch-1", "has_run": True}


def test_missing_source_is_stored_without_calling_the_judge(monkeypatch):
    def refuse_to_judge(*args, **kwargs):
        raise AssertionError("judge should not run when the source is not indexed")

    monkeypatch.setattr(runner, "find_source", lambda path: None)
    monkeypatch.setattr(runner, "judge_answer", refuse_to_judge)
    case = EvalCase(id="q9", question="Q", expected_answer="expected words", source_file="missing.pdf")
    record = runner.evaluate_case(case, "expected words", None, tag="missing")
    assert record["error"] == "source not indexed"
    assert record["verdict"] is None
    assert record["token_f1"] == 1.0
    assert report.load_results()[0]["id"] == "q9"
    assert report.read_summary()["missing"]["errors"] == 1
    assert report.read_summary()["missing"]["evaluated"] == 0

