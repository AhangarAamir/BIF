"""Where an uploaded file goes in the corpus, so its Document Center link is right.

A browser only reveals paths relative to the folder the user picked, never where
that folder sits in the Document Center. So the base is recovered from the path:

  1. a `sites` folder         -> keep from `sites` down     (sites/Regulatory/KGD6/...)
  2. a `Document Center` folder -> keep what is after it    (JOA/New JOA/x.pdf)
  3. a family folder JOA, JAO, PEL, PML, PSC, RSC -> keep from it
  4. otherwise                -> "save under" folder + path (user decides; we suggest)

The corpus folder mirrors the Document Center root, and links are built from the
corpus path (bif.domain.citation_url), so correct placement means correct links.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from bif.config import CORPUS_DIR
from bif.domain import family_for

DOC_CENTER_FAMILIES = {"JOA", "JAO", "PEL", "PML", "PSC", "RSC"}
_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f]')


def safe_parts(path: str) -> list[str]:
    """Path segments with '..', '.', empty and drive/absolute parts removed."""
    parts = [p.strip() for p in (path or "").replace("\\", "/").split("/")]
    return [_UNSAFE.sub("_", p) for p in parts if p and p not in {".", ".."}]


def anchor(parts: list[str]) -> tuple[Optional[list[str]], str]:
    """The part of the path that maps onto the Document Center tree, if recognisable."""
    lowered = [p.lower() for p in parts]
    folders = parts[:-1]
    if "sites" in lowered[:-1]:
        return parts[lowered.index("sites"):], "sites folder"
    if "document center" in [p.lower() for p in folders]:
        i = lowered.index("document center")
        return parts[i + 1:], "Document Center folder"
    for i, part in enumerate(folders):
        if part.upper() in DOC_CENTER_FAMILIES:
            return parts[i:], f"{part.upper()} folder"
    return None, ""


def place(raw_path: str, folder: str = "", keep_top: bool = True, auto_anchor: bool = True) -> tuple[str, str]:
    """(relative path inside the corpus, how it was decided)."""
    parts = safe_parts(raw_path)
    if not parts:
        return "", "empty name"
    if auto_anchor:
        anchored, how = anchor(parts)
        if anchored:
            return "/".join(anchored), f"detected from the {how}"
    if not keep_top and len(parts) > 1:
        parts = parts[1:]
    base = safe_parts(folder)
    return "/".join([*base, *parts]), ("under “" + "/".join(base) + "”") if base else "corpus root"


def corpus_folders(limit: int = 5000) -> list[str]:
    root = CORPUS_DIR.resolve()
    out = []
    for path in root.rglob("*"):
        if path.is_dir() and not any(p.startswith(".") for p in path.relative_to(root).parts):
            out.append(path.relative_to(root).as_posix())
            if len(out) >= limit:
                break
    return sorted(out)


def suggest_base(top_names: Iterable[str]) -> tuple[str, str]:
    """Best guess for the "save under" folder when no path anchors the upload."""
    tops = [t for t in {t.strip() for t in top_names if t and t.strip()}]
    if len(tops) != 1:
        return "", ""
    top = tops[0]
    low = top.lower()
    if top.upper() in DOC_CENTER_FAMILIES or low in {"sites", "document center"}:
        return "", f"“{top}” is already a Document Center root folder"
    # 1) The same folder name already exists somewhere in the corpus: reuse its parent.
    for existing in corpus_folders():
        parts = existing.split("/")
        if parts[-1].lower() == low and len(parts) > 1:
            parent = "/".join(parts[:-1])
            return parent, f"the corpus already has “{existing}”"
    # 2) A known family sub-folder name ("New JOA", "OLD PML", "Domestic" is not one).
    family = family_for(top)
    if family and family.code in DOC_CENTER_FAMILIES and low != family.code.lower():
        return family.code, f"“{top}” looks like a {family.code} sub-folder"
    # 3) A SharePoint site folder.
    if low == "regulatory":
        return "sites", "“Regulatory” sits under sites/ in the Document Center"
    return "", ""
