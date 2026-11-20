# BIF — Legal Research Agent

An [Agno](https://docs.agno.com) agent that answers questions about contracts and regulatory
documents (PSCs, JOAs, PMLs, DGH / MoPNG letters, minutes, amendments) **only from your PDFs**,
with every statement linked to the clause and page it came from.

It covers the same job as `aamir-rag`, rebuilt for accuracy, and it runs on **any OpenAI-compatible
model**: a local Ollama model or a paid OpenAI model. Switching between them is a dropdown in the UI.

## Quick start

```bash
uv sync
cp .env.example .env                 # pick a model, embedding model and corpus folder
cd ui && npm install && npm run build && cd ..

uv run bif ingest                    # index everything under CORPUS_DIR
uv run bif serve                     # http://127.0.0.1:8000
```

Other commands:

```bash
uv run bif ask "What does Article 10.7 of the KG-D6 PSC say?"
uv run bif ingest PSC/Domestic --force     # re-index one folder
uv run bif ingest --prune                  # also drop index rows for deleted files
uv run bif reembed                         # after changing the embedding model
uv run bif status
uv run pytest                              # offline tests (no model needed)
```

## Models: open-source or paid, same agent

A **profile** is an OpenAI-compatible endpoint plus the wire API to use:

| field | example (Ollama) | example (OpenAI) |
|---|---|---|
| base URL (up to `/v1`) | `http://localhost:11434/v1` | `https://api.openai.com/v1` |
| API key | *(empty)* | `sk-…` |
| model | `qwen3:8b` | `gpt-6-luna` |
| API | **Chat Completions** → Agno `OpenAILike` | **Responses** → Agno `OpenAIResponses` |
| thinking | `none` / low / medium / high | none … xhigh, or provider default |

Use **Responses** for OpenAI. Its reasoning models (gpt-5 / gpt-6 class) refuse function tools
with reasoning on `/v1/chat/completions` ("Function tools with reasoning_effort are not supported
… use /v1/responses"), and the Responses API keeps their reasoning between tool calls (Agno chains
turns with `previous_response_id`). Use **Chat Completions** for Ollama, vLLM, LM Studio, Groq,
OpenRouter and most other providers. The OpenAI preset selects Responses automatically, and
profiles saved before this setting existed are migrated the same way on startup. On Responses
you can also stream a reasoning summary into the research trail (some OpenAI orgs must be
verified first).

Add profiles on the **Models** page (presets for Ollama, OpenAI, OpenRouter, Groq, Together, vLLM,
LM Studio, or any custom endpoint). **Fetch** lists the endpoint's models, **Test connection**
makes a real call with a function tool attached (as the agent does, so tool/reasoning
incompatibilities show up here rather than mid-answer), and the switcher at the top of the chat changes the live agent without a
restart. API keys stay on the server (`data/settings.json`, mode 600) and are shown masked.

Embeddings are configured separately (any `/v1/embeddings` endpoint). Changing the embedding model
requires **Re-embed** on the Library page; keyword search keeps working in the meantime.

### Ollama: raise the context window

Ollama loads models with a **4,096-token context** by default and silently drops the start of
longer prompts, which removes the agent's instructions. A research turn needs about 12k+ tokens.
**Test connection** detects this. Fix it once on the Ollama server:

```bash
# systemd: sudo systemctl edit ollama  ->  Environment="OLLAMA_CONTEXT_LENGTH=32768"
OLLAMA_CONTEXT_LENGTH=32768 ollama serve
```

or create a variant: a `Modelfile` with `FROM qwen3:8b` and `PARAMETER num_ctx 32768`, then
`ollama create qwen3:8b-32k -f Modelfile`. Set the profile's **Thinking** to `none` on reasoning
models (Qwen3, gpt-oss) unless you want slower, longer answers. Models of 7B+ give noticeably
better answers than 2B ones.

## What changed from aamir-rag, and why it is more accurate

| | aamir-rag | BIF |
|---|---|---|
| Retrieval | keyword page scan of raw PDFs at query time; needs most query words on one page; first matching page per file | hybrid **BM25 + vectors** fused with reciprocal rank fusion, plus exact clause-number and defined-term lists and a phrase list |
| Chunks | recursive split + one LLM call **per chunk** to label metadata | deterministic legal structure: Article → clause → definition, schedules/annexes, TOC detection, page ranges; **one** optional LLM call **per document** |
| Clause lookup | regex slice at query time | `get_clause("10.7", "KG-D6 PSC")` returns the exact clause with sub-clauses |
| Abbreviations (KG-D6 = KGD6 = KG-DWN-98/3, PSC, MoPNG…) | the model is asked to expand them | expanded in code on every search and in document aliases |
| Named document | prompt rule "never substitute" | resolved against aliases; an unindexed document is **reported**, never silently swapped |
| Citation links | the model builds URLs from prompt rules | links built by the server from the index |
| Hallucinated citations | not checked | post-hook verifies every `[C…]` tag and every quotation against what was retrieved in that turn, then writes the References |
| Prompt | ~1,400 lines | ~90 lines; rules moved into code so small models follow them |

Parser details that matter on real contracts: running headers/footers and page numbers are
removed (but never a line that starts with `ARTICLE`/`Schedule`/a clause number); a numbered line
only starts a clause if it matches the current article, moves forward, and does not continue a
reference (`… under Article\n10.2 above`, `12.5 per cent`); OCR-style numbers (`ARTICLE IO`) and
roman numerals are read; long clauses are split at paragraph / (a)(i) boundaries with the clause
header repeated.

### Retrieval benchmark

`tests/bench_retrieval.py` runs 15 questions (clause lookups, definitions with typos, premise
checks, cross-references, abbreviations, semantic questions) through both systems on the synthetic
corpus in `tests/fixtures/build_corpus.py`. A hit means the right file *and* the passage that
contains the answer.

| | hit@1 | hit@3 |
|---|---|---|
| BIF hybrid search (questions as typed) | 80% | 100% |
| aamir-rag `search_context` (questions as typed) | 33% | 33% |
| aamir-rag `search_context` (short keyword queries + folder hints) | 27% | 27% |

The corpus is small and was written for this project, so treat these as a regression check, not a
general claim. Run it on your own documents by adding cases:

```bash
DATA_DIR=... CORPUS_DIR=... uv run python tests/bench_retrieval.py --aamir ../aamir-rag --verbose
```

## How an answer is produced

1. **Query Agent** (`query-agent`) reads the current message and calls tools:
   `get_clause`, `find_definition`, `search_documents`, `read_pages`, `list_documents`, `think`.
2. Every passage a tool returns is tagged `[C<id>]` and lists the clauses it refers to, so the
   agent can follow cross-references.
3. The answer cites tags inline. A post-hook (`bif/agent/verify.py`) removes malformed tags, flags
   tags that were not retrieved and quotes that are not verbatim (pieces between `…` and `[…]` are
   checked separately), then appends a **References** section with links to the PDF page.
4. The UI turns tags into numbered chips; clicking one opens the passage beside the chat.

An **Ingest Agent** (`ingest-agent`) is also exposed for chat-driven indexing.

### Live reads of the original files

Besides the index, the agent can open the source file at question time (`bif/agent/source_tools.py`):

| tool | reads | used for |
|---|---|---|
| `read_source_pages(document, page, keep_layout)` | PDF pages via poppler `pdftotext` (`-layout` keeps table columns), or Markdown/text pages | exact wording, tables and schedules, files not indexed yet |
| `read_markdown_section(document, heading)` | a Markdown section by number (`14.2`, `21A`) or title, with its sub-sections | Markdown corpora |
| `grep_source(pattern, document, folder)` | raw text of every file, page by page, with surrounding lines | exact phrases, numbers, names |

The commands are fixed argument lists (no shell, nothing the model can compose), run with a
timeout, and only on files inside `CORPUS_DIR`; without poppler they fall back to `pypdf` in the
same environment. Each result lists the `[C…]` tags of the indexed passages on the same pages, so
answers stay citable, and quotes taken from live reads are accepted by the verifier.

Markdown files are parsed by heading: `## 14. Equality…` is Article 14, `### 14.2 …` is clause
14.2 (lettered articles such as `21A` included), and each passage carries its heading path.

## The UI

- **Research**: streaming answers, a live research trail (each search / clause read), numbered
  citations with a source drawer, a verification badge, feedback buttons, session history,
  light and dark themes.
- **Library**: drag-and-drop upload (indexed straight away), corpus scan, progress, per-document
  outline of articles / clauses / definitions, pages that need OCR.
- **Models**: profiles, presets, model fetch, connection test, embeddings, ingest model.
- **Embed widget**: one script tag adds a floating launcher to any intranet page:

```html
<script src="http://127.0.0.1:8000/widget.js" data-title="Legal Research" data-color="#4f46e5" defer></script>
```

For UI development: `cd ui && BIF_API=http://127.0.0.1:8000 npm run dev`.

## API

AgentOS endpoints (same shape as aamir-rag): `POST /agents/query-agent/runs` (SSE),
`GET /sessions`, `GET /sessions/{id}/runs`. App endpoints under `/api`: `status`, `settings`,
`settings/profiles`, `settings/active`, `settings/embedding`, `models/list`, `models/test`,
`documents`, `documents/upload`, `ingest`, `reembed`, `jobs`, `chunks`, `search`, `feedback`.
Files are served from `/files/<path>`. Interactive docs: `/docs`.

```bash
curl -X POST http://127.0.0.1:8000/agents/query-agent/runs \
  -F "message=What is the participating interest of RIL?" -F stream=false
```

Set `ADMIN_TOKEN` to require an `X-Admin-Token` header on settings, ingest and delete endpoints
(the UI has a field for it).

## Layout

```
src/bif/
  config.py, settings.py, models.py   paths, model profiles, OpenAILike factory
  domain.py                           glossary, document families, citation links
  ingest/extract.py                   pdftotext / pypdf, header & footer removal
  ingest/structure.py                 article / clause / definition parser
  ingest/pipeline.py                  profile, context headers, embeddings, index writes
  index/store.py                      SQLite: documents, pages, chunks, FTS5, vectors
  index/vectors.py                    embeddings client + in-memory cosine index
  index/search.py                     hybrid search, document resolution, exact lookups
  agent/tools.py, prompts.py          research toolkit and instructions
  agent/verify.py                     citation / quote verification + References
  agent/agents.py, server.py          Agno agents, AgentOS + API
ui/                                    React app (Vite)
tests/                                 offline tests, fixture corpus, retrieval benchmark
```

## Not carried over yet

aamir-rag's observability dashboard (per-run cost / latency charts) and its reviewer-approved
"learning" loop are not ported. Run metrics (duration, tokens, model) are shown under each answer
and feedback is stored in `data/index.db` (`feedback` table), so both can be added on top.
Scanned pages without a text layer are reported but not OCR'd; run `ocrmypdf` on them first.
