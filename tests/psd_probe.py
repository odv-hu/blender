"""Throwaway probe for #21: does the image editor read the layered 16-bit PSD
that odv_tools would write?

Writes six PSDs from synthetic data, 3120 x 2080, 16-bit RGB, two layers:

    top     "matid"   Normal, 100 %, hidden, opaque flat colours
    bottom  "beauty"  Normal, 100 %, visible, alpha as layer transparency

The files differ only in how the layers are stored:

    1_raw.psd               channels uncompressed
    2_zip.psd               channels ZIP (zlib), no prediction
    3_zippred.psd           channels ZIP with prediction (per-row 16-bit deltas)
    4_zippred_rawcomp.psd   as 3, but the merged composite uncompressed
    5_raw_lr16.psd          as 1, layer info in the 'Lr16' block
    6_zippred_lr16.psd      as 3, layer info in the 'Lr16' block

Files 1-4 keep the layer info in the standard layer section; 5-6 put it in
the 'Lr16' tagged block, where some writers store 16-bit layers instead. The
merged composite (beauty over transparency) uses the layers' compression,
except in 4; its colour is flattened over white, as the format expects.

What to check in the editor: a 16-bit RGB document with transparency; layers
"beauty" and "matid" with matid hidden, both Normal at 100 %; a transparent
hole top right and an alpha ramp along the top edge; a smooth grey ramp along
the bottom edge (visible bands there would mean 8-bit).

Run with any Python 3 that has numpy (Blender's bundled Python has it):

    python3 tests/psd_probe.py <output folder>
    blender --factory-startup -b --python tests/psd_probe.py -- <output folder>

Prints each file's size and write time. Not part of the extension; to be
replaced by a writer module in odv_tools once the format is confirmed.
"""
import os
import struct
import sys
import time
import zlib

import numpy as np

W, H = 3120, 2080
MAX = 65535
ZLIB_LEVEL = 6

VARIANTS = [  # name, layer compression, composite compression, Lr16 block
    ("1_raw", 0, 0, False),
    ("2_zip", 2, 2, False),
    ("3_zippred", 3, 3, False),
    ("4_zippred_rawcomp", 3, 0, False),
    ("5_raw_lr16", 0, 0, True),
    ("6_zippred_lr16", 3, 3, True),
]


# --- synthetic data ---------------------------------------------------------

def to16(a):
    return np.round(np.clip(a, 0.0, 1.0) * MAX).astype(np.uint16)


def synthetic():
    """Return beauty (H, W, 4) and matid (H, W, 4) as uint16."""
    rng = np.random.default_rng(21)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    u, v = x / (W - 1), y / (H - 1)

    rgb = np.stack([0.15 + 0.6 * u, 0.25 + 0.45 * v, 0.65 - 0.35 * u * v], -1)
    for cx, cy, rad, col in [(0.30, 0.55, 0.18, (0.9, 0.5, 0.2)),
                             (0.60, 0.40, 0.12, (0.2, 0.7, 0.4)),
                             (0.45, 0.75, 0.10, (0.3, 0.3, 0.8))]:
        m = np.clip((rad - np.hypot((u - cx) * W / H, v - cy)) / 0.01, 0, 1)[..., None]
        rgb = rgb * (1 - m) + np.array(col, np.float32) * m
    # Render-like grain: about half an 8-bit level, so the low byte is noise.
    rgb += rng.normal(0.0, 0.002, rgb.shape).astype(np.float32)
    # 16-bit check strip along the bottom: grey 0.45 -> 0.47, no grain.
    strip = v > 0.95
    rgb[strip] = (0.45 + 0.02 * u[strip])[:, None]

    alpha = np.ones((H, W), np.float32)
    top = v < 0.05
    alpha[top] = u[top]                                   # alpha ramp 0 -> 1
    d = np.hypot((u - 0.82) * W / H, v - 0.30)
    alpha = np.minimum(alpha, np.clip((d - 0.08) / 0.04, 0, 1))  # feathered hole
    beauty = to16(np.concatenate([rgb, alpha[..., None]], -1))

    # Material ID: flat colours in 40 Voronoi cells, opaque.
    pts = rng.random((40, 2)) * [W, H]
    best = np.full((H, W), np.inf, np.float32)
    idx = np.zeros((H, W), np.int16)
    for i, (px, py) in enumerate(pts):
        d2 = (x - px) ** 2 + (y - py) ** 2
        m = d2 < best
        best[m] = d2[m]
        idx[m] = i
    cols = rng.integers(0, MAX, (40, 3), dtype=np.uint16, endpoint=True)
    matid = np.concatenate([cols[idx], np.full((H, W, 1), MAX, np.uint16)], -1)
    return beauty, matid


# --- PSD writer ---------------------------------------------------------------

def encode(plane, comp):
    """Encode a (rows, W) uint16 array: 0 raw, 2 ZIP, 3 ZIP with prediction."""
    if comp == 3:
        d = plane.copy()
        d[:, 1:] -= plane[:, :-1]          # uint16 wraps, as the format expects
        plane = d
    data = plane.astype(">u2").tobytes()
    return data if comp == 0 else zlib.compress(data, ZLIB_LEVEL)


def pascal(name):
    b = name.encode("ascii", "replace")[:255]
    s = bytes([len(b)]) + b
    return s + b"\0" * (-len(s) % 4)


def tagged(key, data):
    data += b"\0" * (-len(data) % 4)
    return b"8BIM" + key + struct.pack(">I", len(data)) + data


def luni(name):
    u = name.encode("utf-16-be")
    return tagged(b"luni", struct.pack(">I", len(u) // 2) + u)


def write_psd(path, layers, composite, comp, comp_composite, lr16):
    """layers: bottom first, (name, blend key, visible, [(channel id, plane)])."""
    nch = len(composite)
    records, chandata = [], []
    for name, blend, visible, chans in layers:
        enc = [(cid, encode(p, comp)) for cid, p in chans]
        rec = struct.pack(">4iH", 0, 0, H, W, len(enc))
        rec += b"".join(struct.pack(">hI", cid, 2 + len(d)) for cid, d in enc)
        flags = 0x08 | (0 if visible else 0x02)          # 0x02 set = hidden
        rec += b"8BIM" + blend + struct.pack(">BBBx", 255, 0, flags)
        ranges = b"\x00\x00\xff\xff" * 2 * (1 + nch)     # default blend-if ranges
        extra = (struct.pack(">I", 0)                     # no layer mask
                 + struct.pack(">I", len(ranges)) + ranges
                 + pascal(name) + luni(name))
        records.append(rec + struct.pack(">I", len(extra)) + extra)
        for _, d in enc:
            chandata += [struct.pack(">H", comp), d]

    # Negative count: the composite's first extra channel is its transparency.
    info = struct.pack(">h", -len(layers)) + b"".join(records) + b"".join(chandata)
    info += b"\0" * (-len(info) % 4)
    if lr16:
        lmi = struct.pack(">II", 0, 0) + tagged(b"Lr16", info)
    else:
        lmi = struct.pack(">I", len(info)) + info + struct.pack(">I", 0)

    with open(path, "wb") as f:
        f.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, nch, H, W, 16, 3))  # RGB
        f.write(struct.pack(">I", 0))          # colour mode data
        f.write(struct.pack(">I", 0))          # image resources
        f.write(struct.pack(">I", len(lmi)) + lmi)
        f.write(struct.pack(">H", comp_composite))
        f.write(encode(np.concatenate(composite, 0), comp_composite))


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    out = args[0]
    os.makedirs(out, exist_ok=True)

    t = time.perf_counter()
    beauty, matid = synthetic()
    print(f"synthetic data: {time.perf_counter() - t:.1f} s")
    b = [beauty[..., i] for i in range(4)]
    m = [matid[..., i] for i in range(4)]
    layers = [  # bottom first
        ("beauty", b"norm", True, [(-1, b[3]), (0, b[0]), (1, b[1]), (2, b[2])]),
        ("matid", b"norm", False, [(-1, m[3]), (0, m[0]), (1, m[1]), (2, m[2])]),
    ]
    # Merged result = the beauty (matid is hidden). By convention the composite's
    # colour is flattened over white; readers divide the white back out.
    a = beauty[..., 3:].astype(np.float32) / MAX
    flat = to16((beauty[..., :3].astype(np.float32) / MAX) * a + (1.0 - a))
    composite = [flat[..., 0], flat[..., 1], flat[..., 2], b[3]]

    print(f"{'file':28} {'MB':>8} {'s':>6}")
    for name, comp, comp_composite, lr16 in VARIANTS:
        path = os.path.join(out, f"odv_psd_probe_{name}.psd")
        t = time.perf_counter()
        write_psd(path, layers, composite, comp, comp_composite, lr16)
        dt = time.perf_counter() - t
        print(f"{os.path.basename(path):28} {os.path.getsize(path) / 1e6:8.1f} {dt:6.1f}")


if __name__ == "__main__":
    main()
