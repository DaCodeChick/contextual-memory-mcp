from core.ranking import rank_memory


def test_pinning_and_weighting_raise_score() -> None:
    baseline = rank_memory(
        vector_score=0.7,
        lexical_score=0.3,
        graph_score=0.2,
        importance=1.0,
        confidence=0.5,
        source_quality=0.5,
        access_count=0,
        pinned=False,
    )
    promoted = rank_memory(
        vector_score=0.7,
        lexical_score=0.3,
        graph_score=0.2,
        importance=2.0,
        confidence=1.0,
        source_quality=1.0,
        access_count=100,
        pinned=True,
    )
    assert promoted.score > baseline.score
    assert promoted.pinned == 0.05


def test_ranking_score_is_bounded() -> None:
    result = rank_memory(
        vector_score=5.0,
        lexical_score=5.0,
        graph_score=5.0,
        importance=50.0,
        confidence=50.0,
        source_quality=50.0,
        access_count=1_000_000,
        pinned=True,
    )
    assert result.score == 1.0
