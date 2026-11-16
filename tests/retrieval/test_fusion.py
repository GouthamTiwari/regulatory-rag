"""RRF fusion arithmetic, checked against hand-computed values."""

import pytest

from regrag.retrieval.fusion import rrf_fuse
from tests.fakes import make_chunk


def ids(chunks):
    return [c.chunk_id for c in chunks]


def test_hand_computed_example():
    # List A: 1, 2, 3   List B: 3, 1   (k = 60)
    # chunk 1: 1/61 + 1/62 = 0.032522
    # chunk 3: 1/63 + 1/61 = 0.032266
    # chunk 2: 1/62        = 0.016129
    a = [make_chunk(1), make_chunk(2), make_chunk(3)]
    b = [make_chunk(3), make_chunk(1)]
    fused = rrf_fuse([a, b], k=60, top_k=10)
    assert ids(fused) == [1, 3, 2]
    expected = [1 / 61 + 1 / 62, 1 / 63 + 1 / 61, 1 / 62]
    assert [round(c.fused_score, 6) for c in fused] == [round(x, 6) for x in expected]


def test_chunk_in_both_lists_beats_rank_one_in_only_one():
    # chunk 9 is rank 1 in list A only: 1/61 = 0.016393
    # chunk 5 is rank 2 in both lists:  2/62 = 0.032258, so it wins
    a = [make_chunk(9), make_chunk(5)]
    b = [make_chunk(7), make_chunk(5)]
    assert rrf_fuse([a, b])[0].chunk_id == 5


def test_one_empty_list_keeps_the_other_order():
    a = [make_chunk(4), make_chunk(2), make_chunk(8)]
    assert ids(rrf_fuse([a, []])) == [4, 2, 8]
    assert rrf_fuse([[], []]) == []


def test_ties_are_broken_by_chunk_id_for_repeatable_output():
    # Each chunk is rank 1 in exactly one list, so the scores are equal.
    fused = rrf_fuse([[make_chunk(20)], [make_chunk(10)]])
    assert ids(fused) == [10, 20]


def test_top_k_is_respected():
    a = [make_chunk(i) for i in range(1, 41)]
    assert len(rrf_fuse([a], top_k=30)) == 30


def test_original_ranks_are_kept_and_inputs_not_modified():
    kw = make_chunk(1, keyword_rank=1, keyword_score=0.8)
    vec = make_chunk(1, vector_rank=3, vector_score=0.71)
    (fused,) = rrf_fuse([[kw], [vec]])
    assert (fused.keyword_rank, fused.vector_rank) == (1, 3)
    assert fused.vector_score == pytest.approx(0.71)
    assert kw.fused_score is None and kw.vector_rank is None  # inputs untouched
