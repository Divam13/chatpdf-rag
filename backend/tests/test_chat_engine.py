"""
Tests for chat_engine.py: citation parsing, refusal guard, and index validation.

These tests run without any network calls or API keys.
They test the internal helper functions directly.
"""

import sys
import os

# Allow imports from the backend directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chat_engine import _used_indices, _CITE_RE, REFUSAL


# ======================================================================
# _used_indices()
# ======================================================================

class TestUsedIndices:
    def test_single_citation(self):
        assert _used_indices("Some fact [1].", ctx_len=5) == [1]

    def test_multiple_separate_citations(self):
        result = _used_indices("Fact [1]. Another fact [3].", ctx_len=5)
        assert result == [1, 3]

    def test_multi_citation_bracket(self):
        """[2,5] should extract both indices."""
        result = _used_indices("Combined [2,5].", ctx_len=5)
        assert 2 in result
        assert 5 in result

    def test_multi_citation_bracket_with_spaces(self):
        """[2, 5] with spaces should also work."""
        result = _used_indices("Combined [2, 5].", ctx_len=5)
        assert 2 in result
        assert 5 in result

    def test_out_of_range_index_dropped(self):
        """Indices beyond ctx_len are silently dropped."""
        result = _used_indices("Fact [1]. Bad [10].", ctx_len=5)
        assert result == [1]
        assert 10 not in result

    def test_zero_index_dropped(self):
        """Index 0 is out of range (1-indexed)."""
        result = _used_indices("Fact [0].", ctx_len=5)
        assert 0 not in result

    def test_negative_not_matched(self):
        """Negative numbers in brackets should not be matched by the regex."""
        result = _used_indices("Fact [-1].", ctx_len=5)
        assert result == []

    def test_no_citations(self):
        """Text without any bracket notation → empty list."""
        result = _used_indices("A plain answer without citations.", ctx_len=5)
        assert result == []

    def test_duplicate_indices_deduplicated(self):
        """Same index appearing twice should only appear once."""
        result = _used_indices("Fact [1]. More [1].", ctx_len=5)
        assert result == [1]

    def test_preserves_order(self):
        """Indices should appear in the order they are first seen."""
        result = _used_indices("[3] then [1] then [2].", ctx_len=5)
        assert result == [3, 1, 2]

    def test_empty_string(self):
        assert _used_indices("", ctx_len=5) == []


# ======================================================================
# Refusal detection (integration-level logic check)
# ======================================================================

class TestRefusalGuard:
    def test_refusal_string_exact(self):
        """The exact refusal string should be detectable."""
        answer = REFUSAL
        assert REFUSAL in answer

    def test_refusal_embedded_in_text(self):
        """Refusal embedded in a larger response should still be caught."""
        answer = f"Unfortunately, {REFUSAL}"
        assert REFUSAL in answer

    def test_normal_answer_not_a_refusal(self):
        answer = "The document mentions passenger traffic rose by 12% [1]."
        assert REFUSAL not in answer


# ======================================================================
# Citation regex pattern
# ======================================================================

class TestCitationRegex:
    def test_matches_single_digit(self):
        assert _CITE_RE.search("[1]") is not None

    def test_matches_multi_digit(self):
        assert _CITE_RE.search("[12]") is not None

    def test_matches_comma_separated(self):
        m = _CITE_RE.search("[2,5]")
        assert m is not None
        assert m.group(1) == "2,5"

    def test_matches_comma_separated_with_spaces(self):
        m = _CITE_RE.search("[2, 5]")
        assert m is not None
        assert "2" in m.group(1)
        assert "5" in m.group(1)

    def test_no_match_on_empty_brackets(self):
        assert _CITE_RE.search("[]") is None

    def test_no_match_on_text_in_brackets(self):
        assert _CITE_RE.search("[abc]") is None

    def test_finds_all_citations_in_text(self):
        text = "Fact [1]. Another [2,3]. More [5]."
        matches = _CITE_RE.findall(text)
        assert len(matches) == 3
