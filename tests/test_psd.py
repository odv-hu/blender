"""Tests of the PSD writer's PackBits encoder (#24), without Blender.

    python3 tests/test_psd.py

Random rows with and without runs, rows of one byte value, long runs that need
several packets, empty input; each row decoded independently of the writer.
"""
import importlib.util
import os
import sys

import numpy as np

spec = importlib.util.spec_from_file_location(
    "odv_psd", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender", "post_output", "psd.py"))
psd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(psd)


def unpack(row):
    out, i = bytearray(), 0
    while i < len(row):
        n = row[i]
        if n < 128:
            out += row[i + 1:i + 2 + n]
            i += 2 + n
        elif n > 128:
            out += row[i + 1:i + 2] * (257 - n)
            i += 2
        else:
            i += 1
    return bytes(out)


def roundtrip(rows):
    data, counts = psd.packbits_rows(rows)
    pos = 0
    for r, c in zip(rows, counts.tolist()):
        assert unpack(data[pos:pos + c]) == r.tobytes()
        pos += c
    assert pos == len(data)
    return len(data)


rng = np.random.default_rng(24)
for _ in range(500):
    n, length = int(rng.integers(1, 8)), int(rng.integers(1, 600))
    rows = rng.integers(0, int(rng.integers(1, 256)), (n, length)).astype(np.uint8)
    if rng.random() < 0.5:
        a, b = sorted(rng.integers(0, length, 2))
        rows[:, a:b] = rng.integers(0, 256)
    roundtrip(rows)
assert roundtrip(np.full((3, 1000), 255, np.uint8)) == 3 * 2 * 8          # 1000 = 7 x 128 + 104
assert roundtrip(np.arange(256, dtype=np.uint8)[None].repeat(2, 0)) == 2 * (256 + 2)
assert psd.packbits_rows(np.zeros((0, 5), np.uint8))[0] == b""
print("PackBits: 500 random cases, long runs and edge cases round-trip")
