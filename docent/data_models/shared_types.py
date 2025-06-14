from typing import List, TypedDict

from docent.data_models.citation import Citation


class EvidenceWithCitation(TypedDict):
    """A piece of evidence with its citations."""

    evidence: str
    citations: List[Citation]
