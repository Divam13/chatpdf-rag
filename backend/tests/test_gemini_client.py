"""
Tests for gemini_client.py: L2 normalization.

These tests run without any network calls or API keys.
"""

import math
import sys
import os

# Allow imports from the backend directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gemini_client import _l2_normalize


class TestL2Normalize:
    def test_output_has_unit_length(self):
        vec = [3.0, 4.0]
        normed = _l2_normalize(vec)
        length = math.sqrt(sum(v * v for v in normed))
        assert abs(length - 1.0) < 1e-6

    def test_high_dimensional_vector(self):
        vec = [float(i) for i in range(1, 769)]  # 768-d like the real embeddings
        normed = _l2_normalize(vec)
        length = math.sqrt(sum(v * v for v in normed))
        assert abs(length - 1.0) < 1e-6

    def test_preserves_direction(self):
        vec = [3.0, 4.0]
        normed = _l2_normalize(vec)
        # Ratio should be preserved
        assert abs(normed[0] / normed[1] - 3.0 / 4.0) < 1e-6

    def test_zero_vector_unchanged(self):
        vec = [0.0, 0.0, 0.0]
        normed = _l2_normalize(vec)
        assert normed == [0.0, 0.0, 0.0]

    def test_already_normalized_vector(self):
        vec = [1.0, 0.0, 0.0]
        normed = _l2_normalize(vec)
        assert abs(normed[0] - 1.0) < 1e-6
        assert abs(normed[1]) < 1e-6
        assert abs(normed[2]) < 1e-6

    def test_negative_values(self):
        vec = [-3.0, 4.0]
        normed = _l2_normalize(vec)
        length = math.sqrt(sum(v * v for v in normed))
        assert abs(length - 1.0) < 1e-6
        assert normed[0] < 0  # sign preserved

    def test_output_length_matches_input(self):
        vec = [1.0, 2.0, 3.0, 4.0, 5.0]
        normed = _l2_normalize(vec)
        assert len(normed) == len(vec)
