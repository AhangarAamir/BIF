"""Query and ingest agents.

Both take their model from the active profile in data/settings.json.
apply_active_model() swaps the model on the live agents after the profile
changes, so switching Ollama -> OpenAI needs no restart.
"""

from __future__ import annotations

from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from bif.agent.prompts import INGEST_INSTRUCTIONS, QUERY_INSTRUCTIONS
from bif.agent.source_tools import SourceFileTools
from bif.agent.tools import LegalResearchTools, LibraryTools
from bif.agent.verify import finalize_answer
from bif.eval.runner import evaluate_answer
from bif.config import NUM_HISTORY_RUNS, SESSIONS_DB, TOOL_CALL_LIMIT
from bif.models import build_chat_model
from bif.settings import ModelProfile, active_profile

QUERY_AGENT_ID = "query-agent"
INGEST_AGENT_ID = "ingest-agent"
SESSIONS_DB_ID = "bif-sessions"

_db: Optional[SqliteDb] = None
_agents: dict[str, Agent] = {}


def sessions_db() -> SqliteDb:
    global _db
    if _db is None:
        _db = SqliteDb(id=SESSIONS_DB_ID, db_file=str(SESSIONS_DB))
    return _db


def build_query_agent(profile: Optional[ModelProfile] = None) -> Agent:
    agent = Agent(
        id=QUERY_AGENT_ID,
        name="Query Agent",
        description="Answers contract and regulatory questions from the indexed documents, with verified citations.",
        model=build_chat_model(profile),
        db=sessions_db(),
        tools=[LegalResearchTools(), SourceFileTools()],
        instructions=QUERY_INSTRUCTIONS,
        add_history_to_context=True,
        num_history_runs=NUM_HISTORY_RUNS,
        max_tool_calls_from_history=0,
        add_datetime_to_context=True,
        tool_call_limit=TOOL_CALL_LIMIT,
        post_hooks=[finalize_answer, evaluate_answer],
        markdown=True,
    )
    _agents[QUERY_AGENT_ID] = agent
    return agent


def build_ingest_agent(profile: Optional[ModelProfile] = None) -> Agent:
    agent = Agent(
        id=INGEST_AGENT_ID,
        name="Ingest Agent",
        description="Indexes PDF and text files from the corpus folder.",
        model=build_chat_model(profile),
        db=sessions_db(),
        tools=[LibraryTools()],
        instructions=INGEST_INSTRUCTIONS,
        markdown=True,
    )
    _agents[INGEST_AGENT_ID] = agent
    return agent


def apply_active_model() -> str:
    profile = active_profile()
    for agent in _agents.values():
        agent.model = build_chat_model(profile)
    return profile.name
