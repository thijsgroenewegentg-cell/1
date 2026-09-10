# /tests/test_qr.py
"""The pairing QR encoder has to work with no extra packages."""

from __future__ import annotations

from utils.qr import encode, svg


def test_a_short_payload_makes_a_version_1_matrix():
    matrix = encode("HELLO")
    assert len(matrix) == 21
    assert all(len(row) == 21 for row in matrix)


def test_finder_patterns_are_present():
    matrix = encode("JARVIS")
    # Top-left finder is a 7x7 dark ring.
    assert matrix[0][0] == 1
    assert matrix[0][6] == 1
    assert matrix[6][0] == 1
    assert matrix[3][3] == 1  # centre of the finder


def test_encoding_is_deterministic():
    assert encode("same") == encode("same")


def test_a_lan_url_fits_in_version_5():
    url = "http://192.168.1.24:8765/?token=abcdefghijklmnop"
    matrix = encode(url)
    assert 21 <= len(matrix) <= 37


def test_svg_is_a_real_image():
    image = svg("http://192.168.0.5:8765/?token=test")
    assert image.startswith("<svg")
    assert 'fill="#000000"' in image
    assert "</svg>" in image
