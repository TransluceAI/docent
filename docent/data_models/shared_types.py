from typing import List, TypedDict

class EvidenceCitation(TypedDict):
    """A citation reference for evidence."""
    start_idx: int
    end_idx: int
    block_idx: int
    transcript_idx: int | None
    action_unit_idx: int | None

class EvidenceWithCitation(TypedDict):
    """A piece of evidence with its citations."""
    evidence: str
    citations: List[EvidenceCitation] 