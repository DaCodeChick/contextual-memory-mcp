from __future__ import annotations

import hashlib
import re
from pathlib import Path

from core.models import MemorySegment, SourceDocument

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
TAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_-]{2,50})")
LABEL_RE = re.compile(r"(?im)^\s*([A-Z][A-Z0-9 _/-]{2,50}):\s*$")
EXPLICIT_RE = re.compile(
    r"(?im)^\s*(?:concepts?|tags?|keywords?)\s*:\s*(.+)$"
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "because",
    "before", "being", "between", "both", "but", "can", "could",
    "does", "each", "from", "have", "into", "keep", "make", "must",
    "not", "only", "other", "same", "should", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "through",
    "use", "using", "very", "was", "were", "what", "when", "where",
    "which", "while", "with", "would", "you", "your",
}


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(
        "\0".join(parts).encode("utf-8")
    ).hexdigest()[:24]
    return f"{prefix}_{digest}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_concept(value: str) -> str:
    value = re.sub(r"[_-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .,:;|/\\").lower()
    return value[:100]


def load_document(path: Path, root: Path) -> SourceDocument:
    content = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    relative = path.relative_to(root).as_posix()
    heading = HEADING_RE.search(content)
    title = (
        heading.group(2).strip()
        if heading
        else path.stem.replace("_", " ").replace("-", " ")
    )
    return SourceDocument(
        source_id=stable_id("src", relative),
        path=path,
        relative_path=relative,
        title=title,
        content=content,
        content_hash=content_hash(content),
        modified_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
    )


def extract_concepts(
    text: str,
    heading: str | None = None,
    limit: int = 18,
) -> list[str]:
    scores: dict[str, float] = {}

    def add(value: str, weight: float) -> None:
        value = normalize_concept(value)
        if len(value) >= 3:
            scores[value] = scores.get(value, 0.0) + weight

    if heading:
        add(heading, 10)
    for tag in TAG_RE.findall(text):
        add(tag, 8)
    for label in LABEL_RE.findall(text):
        add(label, 7)
    for line in EXPLICIT_RE.findall(text):
        for item in re.split(r"[,;|]", line):
            add(item, 9)
    for word in WORD_RE.findall(text):
        normalized = normalize_concept(word)
        if normalized not in STOPWORDS:
            add(normalized, 0.2)

    return [
        name
        for name, _ in sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:limit]
    ]


def _sections(text: str) -> list[tuple[str | None, int, int, str]]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [(None, 0, len(text), text)]

    sections: list[tuple[str | None, int, int, str]] = []
    if matches[0].start() > 0 and text[:matches[0].start()].strip():
        sections.append(
            (
                None,
                0,
                matches[0].start(),
                text[:matches[0].start()],
            )
        )

    for index, match in enumerate(matches):
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        sections.append(
            (
                match.group(2).strip(),
                start,
                end,
                text[start:end],
            )
        )

    return sections


def _window(
    text: str,
    base: int,
    size: int,
    overlap: int,
):
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + size)
        if end < len(text):
            boundary = max(
                text.rfind("\n\n", cursor, end),
                text.rfind("\n", cursor, end),
            )
            if boundary > cursor + size // 2:
                end = boundary

        value = text[cursor:end].strip()
        if value:
            yield base + cursor, base + end, value

        if end >= len(text):
            break
        cursor = max(cursor + 1, end - overlap)


def segment_document(
    doc: SourceDocument,
    size: int,
    overlap: int,
) -> list[MemorySegment]:
    result: list[MemorySegment] = []
    ordinal = 0

    for heading, start, _end, body in _sections(doc.content):
        for char_start, char_end, text in _window(
            body,
            start,
            size,
            overlap,
        ):
            concepts = extract_concepts(text, heading)
            important_heading = heading and any(
                keyword in heading.lower()
                for keyword in (
                    "rule",
                    "required",
                    "constraint",
                    "identity",
                )
            )
            importance = 1.4 if important_heading else 1.0

            result.append(
                MemorySegment(
                    segment_id=stable_id(
                        "seg",
                        doc.source_id,
                        str(ordinal),
                        content_hash(text),
                    ),
                    source_id=doc.source_id,
                    ordinal=ordinal,
                    heading=heading,
                    text=text,
                    char_start=char_start,
                    char_end=char_end,
                    importance=importance,
                    concepts=concepts,
                )
            )
            ordinal += 1

    return result
