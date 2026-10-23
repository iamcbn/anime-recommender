# test/unit/test_ranking_unit.py
"""
Unit tests for franchise collapsing, candidate deduplication, popularity boost weighting, and ranking.

Conforms to Sprint 3 Unit Testing standards:
- Fast, hermetic, isolated execution with zero database, model download, or network dependencies.
- Strict British English documentation without em-dashes.
- Marked with @pytest.mark.unit.
"""

from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest

from backend.rag_pipeline.helper.ranking import (
    Ranker,
    filter_candidates_by_negative_constraints,
)


@pytest.fixture
def mock_ranker():
    """Provides a hermetic Ranker instance with a mocked CrossEncoder."""
    with patch.object(Ranker, "load_cross_encoder", return_value=MagicMock()):
        ranker = Ranker.__new__(Ranker)
        ranker.cross_encoder = MagicMock()
        return ranker


@pytest.mark.unit
def test_normalise_franchise_title():
    """
    Verifies that normalise_franchise_title strips subtitles, brackets, noise keywords
    (such as season, part, movie, arc), and collapses redundant whitespace into a clean franchise key.
    """
    assert Ranker.normalise_franchise_title("Attack on Titan: The Final Season") == "attack on titan"
    assert Ranker.normalise_franchise_title("Jujutsu Kaisen Season 2") == "jujutsu kaisen 2"
    assert Ranker.normalise_franchise_title("Fate/stay night (TV)") == "fate/stay night"
    assert Ranker.normalise_franchise_title("Demon Slayer: Kimetsu no Yaiba - The Movie: Mugen Train") == "demon slayer"
    assert Ranker.normalise_franchise_title("Sword Art Online II") == "sword art online ii"
    assert Ranker.normalise_franchise_title("Fullmetal Alchemist: Brotherhood") == "fullmetal alchemist"


@pytest.mark.unit
def test_franchise_collapsing_deduplication(mock_ranker):
    """
    Verifies that collapse_franchises2 retains the highest-ranked entry of a franchise,
    collapsing sequels, movies, and spin-offs sharing a high token similarity ratio.
    """
    rows = [
        {
            "id": 16498,
            "title_romaji": "Shingeki no Kyojin",
            "title_english": "Attack on Titan",
            "title_userPreferred": "Attack on Titan",
            "popularity": 500000,
            "cross_encoder_score": 2.5,
            "final_rrf_score": 0.12,
        },
        {
            "id": 20958,
            "title_romaji": "Shingeki no Kyojin Season 2",
            "title_english": "Attack on Titan Season 2",
            "title_userPreferred": "Attack on Titan Season 2",
            "popularity": 350000,
            "cross_encoder_score": 1.8,
            "final_rrf_score": 0.10,
        },
        {
            "id": 11061,
            "title_romaji": "Hunter x Hunter (2011)",
            "title_english": "Hunter x Hunter",
            "title_userPreferred": "Hunter x Hunter",
            "popularity": 400000,
            "cross_encoder_score": 2.2,
            "final_rrf_score": 0.11,
        },
        {
            "id": 104578,
            "title_romaji": "Shingeki no Kyojin: The Final Season",
            "title_english": "Attack on Titan: The Final Season",
            "title_userPreferred": "Attack on Titan: The Final Season",
            "popularity": 300000,
            "cross_encoder_score": 1.5,
            "final_rrf_score": 0.08,
        },
    ]
    df = pd.DataFrame(rows)

    collapsed = mock_ranker.collapse_franchises2(df, top_k=5, threshold=90)

    # Attack on Titan Season 2 and Final Season must be collapsed, leaving only Attack on Titan and Hunter x Hunter
    assert len(collapsed) == 2
    retained_ids = collapsed["id"].tolist()
    assert 16498 in retained_ids  # Highest ranked Attack on Titan
    assert 11061 in retained_ids  # Hunter x Hunter
    assert 20958 not in retained_ids  # Sequel collapsed
    assert 104578 not in retained_ids  # Final season collapsed


@pytest.mark.unit
def test_candidate_deduplication_and_rrf_scoring(mock_ranker):
    """
    Verifies that merge_deduplicate merges multiple retrieval lists, filters out seen IDs,
    deduplicates candidate anime by ID, and computes reciprocal rank fusion (RRF) scores.
    """
    # 2 retrieval lists (e.g. dense semantic search and keyword search)
    list1 = [
        {"id": 1, "title_romaji": "Anime One", "popularity": 100},
        {"id": 2, "title_romaji": "Anime Two", "popularity": 200},
        {"id": 3, "title_romaji": "Anime Three", "popularity": 300},
    ]
    list2 = [
        {"id": 2, "title_romaji": "Anime Two", "popularity": 200},
        {"id": 4, "title_romaji": "Anime Four", "popularity": 400},
    ]

    # Exclude ID 3 via seen_ids
    merged_df = mock_ranker.merge_deduplicate([list1, list2], seen_ids={3})

    assert len(merged_df) == 3
    ids = merged_df["id"].tolist()
    assert 3 not in ids  # Skipped via seen_ids
    assert ids[0] == 2  # Appears in both lists, so highest RRF score

    # Check RRF score calculation:
    # ID 2 was rank 2 in list1 (score 1/(20+2)) and rank 1 in list2 (score 1/(20+1))
    expected_score_id2 = (1.0 / 22.0) + (1.0 / 21.0)
    actual_score_id2 = merged_df.loc[merged_df["id"] == 2, "retrieval_rrf_score"].iloc[0]
    assert pytest.approx(actual_score_id2, rel=1e-4) == expected_score_id2


@pytest.mark.unit
def test_reorder_popularity_boost_and_score_normalisation(mock_ranker):
    """
    Verifies that reorder calculates final hybrid RRF scores incorporating
    Cross-Encoder rankings and soft popularity boost weighting (log1p(pop) / 100).
    """
    data = [
        {"id": 10, "title_romaji": "Low Pop", "popularity": 10, "description": "desc"},
        {"id": 20, "title_romaji": "High Pop", "popularity": 100000, "description": "desc"},
    ]
    df = pd.DataFrame(data)

    # Identical cross-encoder scores
    rerank_scores = np.array([1.5, 1.5])

    reordered = mock_ranker.reorder(df, rerank_scores)

    assert "final_rrf_score" in reordered.columns
    # High Pop anime must rank first due to popularity boost weighting
    assert reordered.iloc[0]["id"] == 20
    assert reordered.iloc[1]["id"] == 10
    assert reordered.iloc[0]["final_rrf_score"] > reordered.iloc[1]["final_rrf_score"]


@pytest.mark.unit
def test_filter_candidates_by_negative_constraints():
    """
    Verifies that filter_candidates_by_negative_constraints removes candidates
    matching disliked genres or avoided tropes case-insensitively.
    """
    candidates = [
        {"id": 1, "title_romaji": "Safe Show", "genres": ["Action", "Adventure"], "tags": ["Magic"]},
        {"id": 2, "title_romaji": "Horror Show", "genres": ["Horror", "Mystery"], "tags": ["Ghosts"]},
        {"id": 3, "title_romaji": "Harem Show", "genres": ["Comedy", "Romance"], "tags": ["Harem", "School"]},
    ]

    # Filter out horror genre and harem trope
    filtered = filter_candidates_by_negative_constraints(
        candidates,
        avoid_genres=["horror"],
        avoid_tropes=["harem"],
    )

    assert len(filtered) == 1
    assert filtered[0]["id"] == 1
    assert filtered[0]["title_romaji"] == "Safe Show"
