# /utils/qr.py
"""Tiny QR encoder (byte mode, versions 1-5, ECC-L) producing an SVG.

No third-party dependency: pairing a phone with the console has to work
on a fresh install. Version 5 holds a typical LAN URL plus token.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

# total codewords, data codewords, ECC codewords, remainder bits
_VERSIONS = {
    1: (26, 19, 7, 0),
    2: (44, 34, 10, 7),
    3: (70, 55, 15, 7),
    4: (100, 80, 20, 7),
    5: (134, 108, 26, 7),
}

# Byte-mode capacity (data codewords minus 2-byte header).
_BYTE_CAP = {ver: spec[1] - 2 for ver, spec in _VERSIONS.items()}


def _gf_tables() -> Tuple[List[int], List[int]]:
    """Build GF(256) exp/log tables for Reed-Solomon (poly 0x11d)."""
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for i in range(255):
        exp[i] = value
        log[value] = i
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf_tables()


def _gf_mul(left: int, right: int) -> int:
    """Multiply two GF(256) elements."""
    if left == 0 or right == 0:
        return 0
    return _EXP[_LOG[left] + _LOG[right]]


def _rs_generator(nsym: int) -> List[int]:
    """Generator polynomial of degree ``nsym``."""
    poly = [1]
    for i in range(nsym):
        nxt = [0] * (len(poly) + 1)
        coef = _EXP[i]
        for j, term in enumerate(poly):
            nxt[j] ^= term
            nxt[j + 1] ^= _gf_mul(term, coef)
        poly = nxt
    return poly


def _rs_encode(data: Sequence[int], nsym: int) -> List[int]:
    """Systematic Reed-Solomon remainder of length ``nsym``."""
    gen = _rs_generator(nsym)
    ecc = [0] * nsym
    for byte in data:
        factor = byte ^ ecc[0]
        ecc = [*ecc[1:], 0]
        if factor == 0:
            continue
        for i, coef in enumerate(gen[1:]):
            ecc[i] ^= _gf_mul(coef, factor)
    return ecc


def _bits_from_bytes(data: Sequence[int]) -> List[int]:
    """Expand bytes into a list of bits, MSB first."""
    bits: List[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _encode_payload(text: str, version: int) -> List[int]:
    """Byte-mode data + ECC codewords for one version."""
    raw = text.encode("utf-8")
    _, data_cw, ecc_cw, _ = _VERSIONS[version]
    # mode (0100) + 8-bit length (versions 1-9) + payload + 0000 terminator
    bits: List[int] = [0, 1, 0, 0]
    bits.extend((len(raw) >> shift) & 1 for shift in range(7, -1, -1))
    for byte in raw:
        bits.extend((byte >> shift) & 1 for shift in range(7, -1, -1))
    bits.extend([0, 0, 0, 0])
    while len(bits) % 8:
        bits.append(0)
    data = []
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i:i + 8]:
            byte = (byte << 1) | bit
        data.append(byte)
    pad = (0xEC, 0x11)
    i = 0
    while len(data) < data_cw:
        data.append(pad[i % 2])
        i += 1
    data = data[:data_cw]
    return data + _rs_encode(data, ecc_cw)


def _size(version: int) -> int:
    """Module count along one side."""
    return 21 + 4 * (version - 1)


def _reserve(version: int) -> List[List[Optional[int]]]:
    """Blank matrix with function patterns painted and reserved."""
    n = _size(version)
    grid: List[List[Optional[int]]] = [[None] * n for _ in range(n)]

    def fill(x: int, y: int, w: int, h: int, bit: Optional[int]) -> None:
        for row in range(y, y + h):
            for col in range(x, x + w):
                if 0 <= row < n and 0 <= col < n:
                    grid[row][col] = bit

    def finder(x: int, y: int) -> None:
        fill(x - 1, y - 1, 9, 9, 0)
        fill(x, y, 7, 7, 1)
        fill(x + 1, y + 1, 5, 5, 0)
        fill(x + 2, y + 2, 3, 3, 1)

    finder(0, 0)
    finder(n - 7, 0)
    finder(0, n - 7)
    # timing
    for i in range(n):
        if grid[6][i] is None:
            grid[6][i] = 1 if i % 2 == 0 else 0
        if grid[i][6] is None:
            grid[i][6] = 1 if i % 2 == 0 else 0
    # alignment
    if version >= 2:
        pos = 4 * version + 10
        ax, ay = pos, pos
        fill(ax - 2, ay - 2, 5, 5, 1)
        fill(ax - 1, ay - 1, 3, 3, 0)
        grid[ay][ax] = 1
    # format info reserved
    for i in range(9):
        if grid[8][i] is None:
            grid[8][i] = 0
        if grid[i][8] is None:
            grid[i][8] = 0
    for i in range(8):
        grid[8][n - 1 - i] = 0
        grid[n - 1 - i][8] = 0
    grid[8][n - 8] = 1  # dark module
    return grid


_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (y // 2 + x // 3) % 2 == 0,
    lambda x, y: (x * y) % 2 + (x * y) % 3 == 0,
    lambda x, y: ((x * y) % 2 + (x * y) % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + (x * y) % 3) % 2 == 0,
)


def _place(grid: List[List[Optional[int]]], bits: List[int], mask: int) -> None:
    """Zigzag-place data bits, applying ``mask``."""
    n = len(grid)
    cursor = 0
    going_up = True
    x = n - 1
    while x > 0:
        if x == 6:
            x -= 1
        y_range = range(n - 1, -1, -1) if going_up else range(n)
        for y in y_range:
            for dx in (0, -1):
                col = x + dx
                if grid[y][col] is not None:
                    continue
                bit = bits[cursor] if cursor < len(bits) else 0
                cursor += 1
                if _MASKS[mask](col, y):
                    bit ^= 1
                grid[y][col] = bit
        going_up = not going_up
        x -= 2


def _format_bits(mask: int) -> List[int]:
    """15-bit format information for ECC-L + ``mask``."""
    data = (0b01 << 3) | mask  # L = 01
    rem = data << 10
    gen = 0b10100110111
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= gen << (i - 10)
    bits = (data << 10 | rem) ^ 0x5412
    return [(bits >> i) & 1 for i in range(14, -1, -1)]


def _paint_format(grid: List[List[Optional[int]]], mask: int) -> None:
    """Write format information around the finders."""
    bits = _format_bits(mask)
    n = len(grid)
    # bit 0 (LSB) first. ``bits`` is MSB-first, so bit i is bits[14 - i].
    pos = [
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7),  # 0-6
        (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),  # 7-14
    ]
    for i, (x, y) in enumerate(pos):
        grid[y][x] = bits[14 - i]
    pos2 = [(n - 1 - i, 8) for i in range(8)]  # bits 0-7
    pos2 += [(8, n - 7 + i) for i in range(7)]  # bits 8-14
    for i, (x, y) in enumerate(pos2):
        grid[y][x] = bits[14 - i]
    grid[n - 8][8] = 1  # dark module (never part of the format string)


def _penalty(grid: List[List[int]]) -> int:
    """QR penalty score; lower is better."""
    n = len(grid)
    score = 0
    # 1: runs of 5+
    for y in range(n):
        run = 1
        for x in range(1, n):
            if grid[y][x] == grid[y][x - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    for x in range(n):
        run = 1
        for y in range(1, n):
            if grid[y][x] == grid[y - 1][x]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    # 2: 2x2 blocks
    for y in range(n - 1):
        for x in range(n - 1):
            if grid[y][x] == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                score += 3
    # 4: dark proportion
    dark = sum(sum(row) for row in grid)
    percent = (dark * 100) // (n * n)
    score += abs(percent - 50) // 5 * 10
    return score


def encode(text: str) -> List[List[int]]:
    """Return a 0/1 QR matrix for ``text``.

    Args:
        text: The payload (UTF-8). Raises ``ValueError`` if it will not fit
            in version 5 (~106 bytes).

    Returns:
        Square matrix, ``1`` is black.
    """
    payload = text.encode("utf-8")
    version = next((ver for ver, cap in _BYTE_CAP.items() if len(payload) <= cap), None)
    if version is None:
        raise ValueError("pairing URL is too long for a version-5 QR")
    codewords = _encode_payload(text, version)
    bits = _bits_from_bytes(codewords)
    bits.extend([0] * _VERSIONS[version][3])
    best: Optional[List[List[int]]] = None
    best_score = 10 ** 9
    for mask in range(8):
        reserved = _reserve(version)
        _place(reserved, bits, mask)
        _paint_format(reserved, mask)
        matrix = [[int(cell or 0) for cell in row] for row in reserved]
        score = _penalty(matrix)
        if score < best_score:
            best_score = score
            best = matrix
    assert best is not None
    return best


def svg(text: str, module: int = 6, border: int = 4) -> str:
    """Render ``text`` as a crisp SVG QR code.

    Args:
        text: Payload.
        module: Pixel size of one module.
        border: Quiet-zone modules (QR spec minimum is 4).

    Returns:
        An SVG document as a string.
    """
    matrix = encode(text)
    n = len(matrix)
    dim = (n + border * 2) * module
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" '
        f'width="{dim}" height="{dim}" shape-rendering="crispEdges">',
        f'<rect width="{dim}" height="{dim}" fill="#ffffff"/>',
    ]
    for y, row in enumerate(matrix):
        for x, bit in enumerate(row):
            if bit:
                parts.append(
                    f'<rect x="{(x + border) * module}" y="{(y + border) * module}" '
                    f'width="{module}" height="{module}" fill="#000000"/>'
                )
    parts.append("</svg>")
    return "".join(parts)


__all__ = ["encode", "svg"]
