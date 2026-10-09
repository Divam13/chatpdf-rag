"""
Tests for ingest.py: text cleaning and page-isolated chunking.

These tests run without any network calls or API keys.
"""

import math
import sys
import os

# Allow imports from the backend directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import _clean, chunk_spans, TextSpan, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS, MIN_CHUNK_CHARS


# ======================================================================
# _clean()
# ======================================================================

class TestClean:
    def test_soft_hyphen_removal(self):
        assert _clean("optimi\xadzation") == "optimization"

    def test_hyphenated_line_break_joining(self):
        assert _clean("optimi-\nzation") == "optimization"

    def test_hyphenated_line_break_not_joined_without_word_char(self):
        # Hyphen-newline before a non-word char should NOT be joined
        assert _clean("value-\n— next") == "value- — next"

    def test_single_newline_becomes_space(self):
        assert _clean("hello\nworld") == "hello world"

    def test_double_newline_preserved_as_paragraph(self):
        result = _clean("paragraph one\n\nparagraph two")
        assert "\n\n" in result
        assert "paragraph one" in result
        assert "paragraph two" in result

    def test_whitespace_collapsing(self):
        assert _clean("hello   \t  world") == "hello world"

    def test_carriage_return_stripped(self):
        assert _clean("hello\r\nworld") == "hello world"

    def test_empty_input(self):
        assert _clean("") == ""

    def test_only_whitespace(self):
        assert _clean("   \t \n  ") == ""

    def test_leading_trailing_whitespace(self):
        assert _clean("  hello  ") == "hello"


# ======================================================================
# chunk_spans()
# ======================================================================

def _make_span(page: int, text: str, y0: float = 0.0) -> TextSpan:
    """Helper: create a TextSpan with sensible defaults."""
    return TextSpan(
        page=page,
        text=text,
        x0=10.0,
        y0=y0,
        x1=200.0,
        y1=y0 + 20.0,
        page_width=612.0,
        page_height=792.0,
    )


class TestChunkSpans:
    def test_chunks_never_cross_pages(self):
        """Chunks must be page-isolated — no chunk spans two pages."""
        spans = [
            _make_span(1, "A " * 500, y0=10.0),
            _make_span(1, "B " * 500, y0=100.0),
            _make_span(2, "C " * 500, y0=10.0),
            _make_span(2, "D " * 500, y0=100.0),
        ]
        chunks = chunk_spans(spans)
        for chunk in chunks:
            assert chunk.page in (1, 2), f"Unexpected page: {chunk.page}"

        pages = {c.page for c in chunks}
        assert 1 in pages
        assert 2 in pages

    def test_tiny_text_dropped(self):
        """Spans shorter than MIN_CHUNK_CHARS should be dropped."""
        tiny = "Hi."  # well under 120 chars
        spans = [_make_span(1, tiny, y0=10.0)]
        chunks = chunk_spans(spans)
        assert len(chunks) == 0

    def test_bbox_is_union_of_block_boxes(self):
        """Chunk bbox should be the union of all its component span bboxes."""
        span_a = TextSpan(
            page=1, text="A " * 100,
            x0=50.0, y0=100.0, x1=200.0, y1=120.0,
            page_width=612.0, page_height=792.0,
        )
        span_b = TextSpan(
            page=1, text="B " * 100,
            x0=30.0, y0=200.0, x1=250.0, y1=220.0,
            page_width=612.0, page_height=792.0,
        )
        chunks = chunk_spans([span_a, span_b])
        assert len(chunks) >= 1
        # The first chunk should contain both spans since total chars < target
        bbox = chunks[0].bbox
        assert bbox[0] == min(span_a.x0, span_b.x0)  # x0 = 30
        assert bbox[1] == min(span_a.y0, span_b.y0)  # y0 = 100
        assert bbox[2] == max(span_a.x1, span_b.x1)  # x1 = 250
        assert bbox[3] == max(span_a.y1, span_b.y1)  # y1 = 220

    def test_large_text_produces_multiple_chunks(self):
        """Text larger than CHUNK_TARGET_CHARS should produce multiple chunks."""
        big_text = "word " * (CHUNK_TARGET_CHARS // 3)
        spans = [
            _make_span(1, big_text, y0=10.0),
            _make_span(1, big_text, y0=100.0),
            _make_span(1, big_text, y0=200.0),
        ]
        chunks = chunk_spans(spans)
        assert len(chunks) >= 2

    def test_sequential_chunk_indices(self):
        """Chunk indices should be sequential starting from 1."""
        spans = [_make_span(1, "Text block. " * 30, y0=i * 20.0) for i in range(5)]
        chunks = chunk_spans(spans)
        if chunks:
            indices = [c.chunk_index for c in chunks]
            assert indices == list(range(1, len(chunks) + 1))

    def test_empty_input(self):
        """No spans → no chunks."""
        assert chunk_spans([]) == []
