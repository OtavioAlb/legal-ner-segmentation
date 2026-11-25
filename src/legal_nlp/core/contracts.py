"""Minimal canonical, immutable contracts. No dependencies on annotation backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Literal


class AdjudicationStatus(str, Enum):
    CONSOLIDATED = "consolidated"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    EXCLUDED_INVALID = "excluded_invalid"


@dataclass(frozen=True, slots=True)
class Document:
    document_id: str
    text: str
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise ValueError("document_id must be non-empty")
        if not isinstance(self.text, str):
            raise TypeError("document text must be a str")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be non-empty")

    @property
    def sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Span:
    document_id: str
    region_id: str
    task: Literal["NER", "SEG"]
    label: str
    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if not self.document_id or not self.region_id:
            raise ValueError("span requires a document_id and a region_id")
        if self.task not in ("NER", "SEG"):
            raise ValueError("task must be NER or SEG")
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("span requires a label")
        if type(self.start) is not int or type(self.end) is not int:
            raise TypeError("offsets must be integers, not booleans")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("offsets must satisfy 0 <= start < end")
        if not isinstance(self.text, str):
            raise TypeError("span text must be a str")

    def matches_document(self, document: Document) -> bool:
        """Exact character slice check; diagnostic, never a silent correction."""
        if document.document_id != self.document_id:
            return False
        return document.text[self.start:self.end] == self.text


@dataclass(frozen=True, slots=True)
class AnnotationRecord:
    span: Span
    source_system: str
    source_annotation_id: str
    original_reviewer_id: str | None = None
    effective_reviewer_id: str | None = None
    adjudication_status: AdjudicationStatus = AdjudicationStatus.PENDING_REVIEW

    def __post_init__(self) -> None:
        if not self.source_system or not self.source_annotation_id:
            raise ValueError("annotation requires source system and source annotation id")
        if not isinstance(self.adjudication_status, AdjudicationStatus):
            raise TypeError("adjudication_status must be an AdjudicationStatus")
