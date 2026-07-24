from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.models import SourceDocument
from extraction.markdown_parser import content_hash, stable_id

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
}

TEXT_REGION_TYPES = {
    "speech_bubble",
    "thought_bubble",
    "caption",
    "scene_text",
    "clothing_text",
    "surface_text",
    "document_text",
    "ui_text",
    "sound_effect",
    "watermark",
    "other_text",
}

SYSTEM_PROMPT = """You are a general-purpose visual-memory extractor. Analyze the image, not just its OCR.
Return strict JSON only. Describe visual content and separately identify every meaningful text region.

Text classification rules:
- speech_bubble: spoken dialogue inside a bubble/balloon or clearly attached dialogue container.
- thought_bubble: internal thought inside a cloud/thought container.
- caption: narration, editorial overlay, subtitle, label, or non-diegetic explanatory text added over the image.
- scene_text: text that physically belongs to the depicted scene when a narrower type is uncertain.
- clothing_text: text printed, embroidered, patched, or written on clothing or wearable items.
- surface_text: text on signs, walls, vehicles, packages, furniture, screens-as-objects, or other physical surfaces.
- document_text: text on a depicted page, letter, book, form, card, poster, or document where reading is central.
- ui_text: application/game/camera interface text or HUD elements.
- sound_effect: comic/manga sound effects or stylized onomatopoeia.
- watermark: creator mark, logo overlay, stock watermark, or provenance mark.
- other_text: readable text that does not fit above.

Do not classify text on a shirt or sign as a caption merely because it is prominent. Use perspective,
occlusion, curvature, material deformation, container shape, tails/pointers, and scene attachment.
Preserve uncertain readings and lower confidence instead of guessing. Coordinates are normalized 0..1.

Schema:
{
  "summary": "concise overall visual description",
  "subjects": [{"label":"...","description":"...","bbox":[x,y,w,h],"confidence":0.0}],
  "objects": [{"label":"...","description":"...","bbox":[x,y,w,h],"confidence":0.0}],
  "setting": "...",
  "style": "...",
  "text_regions": [{
    "type": "one allowed type",
    "text": "verbatim visible text",
    "normalized_text": "cleaned text without changing meaning",
    "description": "where/how the text appears and what it is attached to",
    "speaker": "name/description or null",
    "bbox": [x,y,w,h],
    "reading_order": 0,
    "ocr_confidence": 0.0,
    "classification_confidence": 0.0
  }],
  "relationships": ["short spatial or semantic relationship"],
  "warnings": ["uncertainty, unreadable text, ambiguity"]
}
"""


@dataclass(slots=True)
class VisualAnalysis:
    summary: str
    subjects: list[dict[str, Any]] = field(default_factory=list)
    objects: list[dict[str, Any]] = field(default_factory=list)
    setting: str = ""
    style: str = ""
    text_regions: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "VisualAnalysis":
        regions: list[dict[str, Any]] = []
        for index, raw in enumerate(value.get("text_regions") or []):
            if not isinstance(raw, dict):
                continue
            region = dict(raw)
            kind = str(region.get("type") or "other_text").strip().lower()
            region["type"] = kind if kind in TEXT_REGION_TYPES else "other_text"
            region["reading_order"] = int(region.get("reading_order", index))
            region["ocr_confidence"] = _confidence(region.get("ocr_confidence"))
            region["classification_confidence"] = _confidence(
                region.get("classification_confidence")
            )
            region["bbox"] = _bbox(region.get("bbox"))
            region["speaker"] = region.get("speaker") or None
            regions.append(region)
        regions.sort(key=lambda item: item["reading_order"])
        return cls(
            summary=str(value.get("summary") or "Visual asset").strip(),
            subjects=_dict_list(value.get("subjects")),
            objects=_dict_list(value.get("objects")),
            setting=str(value.get("setting") or "").strip(),
            style=str(value.get("style") or "").strip(),
            text_regions=regions,
            relationships=[str(x).strip() for x in value.get("relationships") or [] if str(x).strip()],
            warnings=[str(x).strip() for x in value.get("warnings") or [] if str(x).strip()],
        )

    def to_markdown(self, source_name: str) -> str:
        lines = [f"# Visual memory: {source_name}", "", "## Visual summary", self.summary]
        if self.setting:
            lines += ["", f"Setting: {self.setting}"]
        if self.style:
            lines += [f"Style: {self.style}"]
        if self.subjects:
            lines += ["", "## Subjects"]
            for item in self.subjects:
                lines.append(_entity_line(item))
        if self.objects:
            lines += ["", "## Objects"]
            for item in self.objects:
                lines.append(_entity_line(item))
        if self.relationships:
            lines += ["", "## Relationships"] + [f"- {x}" for x in self.relationships]
        lines += ["", "## Text regions"]
        if not self.text_regions:
            lines.append("No readable or meaningful text detected.")
        for index, region in enumerate(self.text_regions, 1):
            text = str(region.get("text") or "").strip() or "[unreadable]"
            normalized = str(region.get("normalized_text") or "").strip()
            lines += [
                "",
                f"### Text region {index}: {region['type']}",
                f"Text: {text}",
                f"Classification: {region['type']}",
                f"Location: {json.dumps(region['bbox'])}",
                f"OCR confidence: {region['ocr_confidence']:.3f}",
                f"Classification confidence: {region['classification_confidence']:.3f}",
            ]
            if normalized and normalized != text:
                lines.append(f"Normalized text: {normalized}")
            if region.get("speaker"):
                lines.append(f"Speaker: {region['speaker']}")
            if region.get("description"):
                lines.append(f"Visual attachment: {region['description']}")
        if self.warnings:
            lines += ["", "## Analysis warnings"] + [f"- {x}" for x in self.warnings]
        return "\n".join(lines).strip() + "\n"


class OpenAICompatibleVisionProvider:
    """Vision extraction through LM Studio, Ollama's OpenAI endpoint, or another compatible server."""

    def __init__(self, *, base_url: str, model: str, api_key: str | None, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def analyze(self, path: Path) -> VisualAnalysis:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract this image into structured visual memory."},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    ],
                },
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Vision analysis failed for {path}: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Vision server returned an unexpected response for {path}") from exc
        if isinstance(content, list):
            content = "".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in content)
        parsed = _parse_json_object(str(content))
        return VisualAnalysis.from_mapping(parsed)


def load_visual_document(path: Path, root: Path, provider: OpenAICompatibleVisionProvider) -> SourceDocument:
    stat = path.stat()
    relative = path.relative_to(root).as_posix()
    binary_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    analysis = provider.analyze(path)
    content = analysis.to_markdown(path.name)
    return SourceDocument(
        source_id=stable_id("src", relative),
        path=path,
        relative_path=relative,
        title=path.stem.replace("_", " ").replace("-", " "),
        content=content,
        content_hash=binary_hash,
        modified_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
    )


def is_visual_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S)
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Vision model did not return a JSON object")
        result = json.loads(value[start : end + 1])
    if not isinstance(result, dict):
        raise RuntimeError("Vision model returned JSON that was not an object")
    return result


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _bbox(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        return [0.0, 0.0, 1.0, 1.0]
    return [_confidence(x) for x in value]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(x) for x in value if isinstance(x, dict)]


def _entity_line(item: dict[str, Any]) -> str:
    label = str(item.get("label") or "item").strip()
    description = str(item.get("description") or "").strip()
    bbox = _bbox(item.get("bbox"))
    confidence = _confidence(item.get("confidence"))
    suffix = f" — {description}" if description else ""
    return f"- {label}{suffix} (bbox={json.dumps(bbox)}, confidence={confidence:.3f})"
