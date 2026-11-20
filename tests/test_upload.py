"""Folder upload: structure kept, unsupported / hidden files skipped, traversal contained."""

from fastapi.testclient import TestClient

from bif.config import CORPUS_DIR


def test_folder_upload_skips_and_continues(indexed_corpus):
    from bif.server import base_app

    client = TestClient(base_app)
    files = [
        ("files", ("a.pdf", b"%PDF-1.4 tiny", "application/pdf")),
        ("files", ("memo.txt", b"royalty note", "text/plain")),
        ("files", ("report.docx", b"x", "application/octet-stream")),
        ("files", (".DS_Store", b"x", "application/octet-stream")),
        ("files", ("evil.txt", b"x", "text/plain")),
        ("files", ("NOEXT", b"x", "application/octet-stream")),
    ]
    data = {
        "paths": [
            "Up/JOA/New JOA/a.pdf",
            "Up/notes/deep/memo.txt",
            "Up/docs/report.docx",
            "Up/.DS_Store",
            "../../../evil.txt",
            "Up/NOEXT",
        ],
        "folder": "batch",
        "ingest": "false",
    }
    res = client.post("/api/documents/upload", files=files, data=data)
    assert res.status_code == 200, res.text
    body = res.json()
    assert sorted(body["saved"]) == ["batch/Up/JOA/New JOA/a.pdf", "batch/Up/notes/deep/memo.txt", "batch/evil.txt"]
    reasons = {s["file"]: s["reason"] for s in body["skipped"]}
    assert reasons["Up/docs/report.docx"] == "unsupported type .docx"
    assert reasons["Up/.DS_Store"] == "hidden file"
    assert reasons["Up/NOEXT"] == "unsupported type (none)"
    assert (CORPUS_DIR / "batch/Up/JOA/New JOA/a.pdf").is_file()
    assert not (CORPUS_DIR.parent / "evil.txt").exists()
