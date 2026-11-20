"""Citation links follow aamir-rag's query-prompt rules (its examples are the expected values)."""

import pytest

from bif.domain import citation_path, citation_url

DC = "https://enp1.ril.com/sites/Regulatory/Document%20Center/"


@pytest.mark.parametrize(
    "rel, label, url",
    [
        # Document Center families, nested folders kept, spaces -> %20
        ("JOA/NEW JOA/file.pdf", "JOA/NEW JOA/file.pdf", DC + "JOA/NEW%20JOA/file.pdf"),
        ("PEL/file.pdf", "PEL/file.pdf", DC + "PEL/file.pdf"),
        ("PML/OLD PML/file.pdf", "PML/OLD PML/file.pdf", DC + "PML/OLD%20PML/file.pdf"),
        ("RSC/file.pdf", "RSC/file.pdf", DC + "RSC/file.pdf"),
        # sites/ files: from sites down, no Document Center inserted
        (
            "sites/Regulatory/KGD6/MINUTESnRESOLUTIONS/OCR/Document Center/file.pdf",
            "sites/Regulatory/KGD6/MINUTESnRESOLUTIONS/OCR/Document Center/file.pdf",
            "https://enp1.ril.com/sites/Regulatory/KGD6/MINUTESnRESOLUTIONS/OCR/Document%20Center/file.pdf",
        ),
        (
            "sites/Regulatory/KGUDWHP/Document Center/KGUDWHP-2018-1/MCR-MCM/file.pdf",
            "sites/Regulatory/KGUDWHP/Document Center/KGUDWHP-2018-1/MCR-MCM/file.pdf",
            "https://enp1.ril.com/sites/Regulatory/KGUDWHP/Document%20Center/KGUDWHP-2018-1/MCR-MCM/file.pdf",
        ),
        # workspace dump segment removed
        ("RSC/aamirWS/data/ril_data/RSC/file.pdf", "RSC/file.pdf", DC + "RSC/file.pdf"),
        ("RSC/aamirWS/data/ril_data/RSC/Sub/file.pdf", "RSC/Sub/file.pdf", DC + "RSC/Sub/file.pdf"),
        # any source type links as .pdf
        ("01_fundamental_rights.md", "01_fundamental_rights.pdf", DC + "01_fundamental_rights.pdf"),
        ("PSC/Notes on KG-D6.txt", "PSC/Notes on KG-D6.pdf", DC + "PSC/Notes%20on%20KG-D6.pdf"),
        ("MCM/minutes 18.06.2019.markdown", "MCM/minutes 18.06.2019.pdf", DC + "MCM/minutes%2018.06.2019.pdf"),
    ],
)
def test_aamir_rag_link_rules(rel, label, url):
    assert citation_path(rel) == label
    assert citation_url(rel) == url
    assert "aamirWS" not in url and "data/ril_data" not in url
