"""Upload placement recovers the Document Center position of a picked folder."""

import pytest

from bif.domain import citation_url
from bif.ingest.placement import place, suggest_base

DC = "https://enp1.ril.com/sites/Regulatory/Document%20Center/"


@pytest.mark.parametrize(
    "raw, folder, keep_top, expected",
    [
        # Picked "JOA": the family folder anchors it.
        ("JOA/New JOA/a.pdf", "", True, "JOA/New JOA/a.pdf"),
        # Picked a parent export folder: everything after "Document Center" is kept.
        ("Export/Regulatory/Document Center/PSC/Domestic/b.pdf", "", True, "PSC/Domestic/b.pdf"),
        # sites paths keep from "sites" down, even with a "Document Center" deeper inside.
        ("backup/sites/Regulatory/KGD6/MINUTESnRESOLUTIONS/OCR/Document Center/m.pdf", "", True,
         "sites/Regulatory/KGD6/MINUTESnRESOLUTIONS/OCR/Document Center/m.pdf"),
        # Anchor wins over a wrong "save under".
        ("JOA/Old JOA/c.pdf", "misc", True, "JOA/Old JOA/c.pdf"),
        # No anchor: goes under the chosen folder, keeping the picked folder's name ...
        ("New JOA/d.pdf", "JOA", True, "JOA/New JOA/d.pdf"),
        # ... or without it.
        ("New JOA/d.pdf", "JOA/New JOA", False, "JOA/New JOA/d.pdf"),
        # Traversal is neutralised.
        ("../../x/../e.pdf", "", True, "x/e.pdf"),
    ],
)
def test_place(raw, folder, keep_top, expected):
    assert place(raw, folder, keep_top)[0] == expected


def test_links_follow_placement():
    rel, _ = place("New JOA/d.pdf", "JOA", True)
    assert citation_url(rel) == DC + "JOA/New%20JOA/d.pdf"


def test_suggestions(indexed_corpus):
    # The fixture corpus has JOA/New JOA, so "New JOA" belongs under "JOA".
    assert suggest_base(["New JOA"])[0] == "JOA"
    assert suggest_base(["Regulatory"])[0] == "sites"
    assert suggest_base(["JOA"])[0] == ""        # already a root folder
    assert suggest_base(["a", "b"])[0] == ""     # several top folders: no guess


def test_scan_drops_entries_for_moved_files(indexed_corpus):
    """Moving a file into the right folder must not leave the old path (and link) behind."""
    from bif.config import CORPUS_DIR
    from bif.index import store
    from bif.ingest.pipeline import ingest_path

    old = CORPUS_DIR / "flat_note.md"
    old.write_text("# Note\n\n## 1. Scope\n\nThis note explains the scope of the moved document in detail.\n")
    ingest_path(None, use_llm=False)
    assert store.find_document_by_path("flat_note.md")

    new = CORPUS_DIR / "PSC" / "Notes" / "flat_note.md"
    new.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new)
    report = ingest_path(None, use_llm=False)
    assert report.removed == ["flat_note.md"]
    assert store.find_document_by_path("PSC/Notes/flat_note.md")
    assert not store.find_document_by_path("flat_note.md")
