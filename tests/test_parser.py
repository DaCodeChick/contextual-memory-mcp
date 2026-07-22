from pathlib import Path

from core.models import SourceDocument
from extraction.markdown_parser import content_hash, segment_document


def test_heading_aware_segmentation() -> None:
    text = "# Character Prompt\n\nIntro text.\n\n## Reference Rules\n\nPreserve identity and eye color."
    doc = SourceDocument("src_test", Path("test.md"), "test.md", "Character Prompt", text, content_hash(text), 0, len(text))
    segments = segment_document(doc, 1000, 100)
    assert len(segments) == 2
    assert segments[1].heading == "Reference Rules"
    assert "reference rules" in segments[1].concepts
    assert segments[1].importance > 1.0
    assert segments[1].identity_key == "section:1:chunk:0"
    assert segments[1].content_hash == content_hash(segments[1].text)
