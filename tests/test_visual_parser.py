from extraction.visual_parser import VisualAnalysis


def test_visual_analysis_preserves_distinct_text_roles() -> None:
    analysis = VisualAnalysis.from_mapping({
        "summary": "A person beside a sign.",
        "text_regions": [
            {"type": "caption", "text": "Earlier that day", "bbox": [0, 0, .4, .1]},
            {"type": "speech_bubble", "text": "Hello", "speaker": "person"},
            {"type": "clothing_text", "text": "STAFF"},
            {"type": "surface_text", "text": "EXIT"},
        ],
    })
    markdown = analysis.to_markdown("scene.png")
    assert "Classification: caption" in markdown
    assert "Classification: speech_bubble" in markdown
    assert "Classification: clothing_text" in markdown
    assert "Classification: surface_text" in markdown


def test_unknown_text_role_is_safely_normalized() -> None:
    analysis = VisualAnalysis.from_mapping({
        "summary": "test",
        "text_regions": [{"type": "alien_kind", "text": "X"}],
    })
    assert analysis.text_regions[0]["type"] == "other_text"
