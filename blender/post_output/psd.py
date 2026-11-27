"""Minimal writer for layered 16-bit RGB PSD files (#21).

Writes only what odv tools needs: full-canvas raster layers with a name,
visibility and blend mode, 16-bit RGB with a transparency channel, and the
merged composite. Uses only numpy and the Python standard library.

Layout, checked in the image editor on Windows (#21):
- layer channels ZIP-compressed with prediction, layer info in the standard
  layer section;
- the merged composite RLE-compressed (PackBits, as Photoshop writes it), because
  the PSD thumbnail handler on Windows does not decode a ZIP composite (#24; it
  was uncompressed before). Its colour is flattened over white, as the format
  expects. write(..., composite_rle=False) still writes it uncompressed.
"""

import struct
import zlib
from collections import namedtuple

import numpy as np

MAX = 65535
RAW, RLE, ZIP, ZIP_PREDICTION = 0, 1, 2, 3
ZLIB_LEVEL = 6

# pixels: (H, W, 3) or (H, W, 4) uint16, straight (not premultiplied) alpha.
# blend: a four-byte PSD blend mode key, such as b"norm".
Layer = namedtuple("Layer", "name pixels visible blend")


def flatten_over_white(rgba):
    """The merged composite of one RGBA layer: colour over white, alpha kept."""
    a = rgba[..., 3:].astype(np.float32) / MAX
    rgb = rgba[..., :3].astype(np.float32) / MAX * a + (1.0 - a)
    out = np.empty_like(rgba)
    out[..., :3] = np.round(np.clip(rgb, 0.0, 1.0) * MAX).astype(np.uint16)
    out[..., 3] = rgba[..., 3]
    return out


def _encode(plane, compression):
    """One channel, (rows, W) uint16 -> bytes."""
    if compression == ZIP_PREDICTION:
        d = plane.copy()
        d[:, 1:] -= plane[:, :-1]          # uint16 wraps, as the format expects
        plane = d
    data = plane.astype(">u2").tobytes()
    return data if compression == RAW else zlib.compress(data, ZLIB_LEVEL)


def packbits_rows(rows):
    """PackBits-encode every row of a (n, L) uint8 array, vectorised.

    Returns (data, counts): the concatenated packets, row after row, and the byte
    count of each row. Runs of three or more equal bytes become repeat packets, the
    rest literal packets; neither crosses a row or exceeds 128 bytes.
    """
    rows = np.ascontiguousarray(rows, dtype=np.uint8)
    n, length = rows.shape
    flat = rows.ravel()
    if flat.size == 0:
        return b"", np.zeros(n, np.int64)
    # runs of equal bytes, never across a row boundary
    new = np.ones(flat.size, bool)
    new[1:] = flat[1:] != flat[:-1]
    new[::length] = True
    run_start = np.flatnonzero(new)
    run_len = np.diff(np.append(run_start, flat.size))
    run_row = run_start // length
    repeat = run_len >= 3
    # consecutive short runs in the same row merge into one literal segment
    seg_new = np.ones(run_start.size, bool)
    seg_new[1:] = repeat[1:] | repeat[:-1] | (run_row[1:] != run_row[:-1])
    seg_idx = np.cumsum(seg_new) - 1
    seg_start = run_start[seg_new]
    seg_len = np.bincount(seg_idx, weights=run_len).astype(np.int64)
    seg_repeat = repeat[seg_new]
    # split segments into packets of at most 128 bytes
    npk = (seg_len + 127) // 128
    pk_seg = np.repeat(np.arange(seg_start.size), npk)
    first = np.cumsum(npk) - npk
    k = np.arange(pk_seg.size) - np.repeat(first, npk)
    pk_start = seg_start[pk_seg] + 128 * k
    pk_len = np.minimum(128, seg_len[pk_seg] - 128 * k)
    pk_repeat = seg_repeat[pk_seg]
    size = np.where(pk_repeat, 2, 1 + pk_len)
    off = np.cumsum(size) - size
    out = np.empty(int(size.sum()), np.uint8)
    out[off] = np.where(pk_repeat, (257 - pk_len) & 0xFF, pk_len - 1).astype(np.uint8)
    rep = np.flatnonzero(pk_repeat)
    out[off[rep] + 1] = flat[pk_start[rep]]
    lit = np.flatnonzero(~pk_repeat)
    if lit.size:
        ll = pk_len[lit]
        total = int(ll.sum())
        within = np.arange(total) - np.repeat(np.cumsum(ll) - ll, ll)
        out[np.repeat(off[lit] + 1, ll) + within] = flat[np.repeat(pk_start[lit], ll) + within]
    counts = np.bincount(pk_start // length, weights=size, minlength=n).astype(np.int64)
    return out.tobytes(), counts


def unpackbits_row(data):
    """Decode one PackBits row (for tests and checks)."""
    out, i = bytearray(), 0
    while i < len(data):
        h = data[i]
        i += 1
        if h < 128:
            out += data[i:i + h + 1]
            i += h + 1
        elif h > 128:
            out += bytes([data[i]]) * (257 - h)
            i += 1
    return bytes(out)


def _rle_planes(planes):
    """The image data section for RLE: byte counts of every row of every channel (two
    bytes each), then the rows, channel after channel. 16-bit samples are encoded as
    their big-endian bytes."""
    rows = np.concatenate([p.astype(">u2").view(np.uint8).reshape(p.shape[0], -1) for p in planes])
    data, counts = packbits_rows(rows)
    if counts.max(initial=0) > 0xFFFF:
        raise ValueError("an RLE row is longer than 65535 bytes")
    return counts.astype(">u2").tobytes() + data


def _pascal(name, pad):
    b = name.encode("ascii", "replace")[:255]
    s = bytes([len(b)]) + b
    return s + b"\0" * (-len(s) % pad)


def _tagged(key, data):
    data += b"\0" * (-len(data) % 4)
    return b"8BIM" + key + struct.pack(">I", len(data)) + data


def _resources(icc):
    if not icc:
        return b""
    data = bytes(icc) + b"\0" * (len(icc) % 2)
    # 1039: ICC profile. Name: empty Pascal string, padded to an even length.
    return b"8BIM" + struct.pack(">H", 1039) + b"\0\0" + struct.pack(">I", len(icc)) + data


def write(path, layers, composite, icc=None, composite_rle=True):
    """Write a layered 16-bit RGB PSD.

    layers: bottom first. composite: (H, W, 4) uint16, the merged result with
    its colour flattened over white (see flatten_over_white). icc: optional
    ICC profile bytes, embedded as the document's colour profile. composite_rle:
    PackBits for the composite (default), else uncompressed.
    """
    h, w = composite.shape[:2]
    nch = composite.shape[2]
    records, chandata = [], []
    for layer in layers:
        px = layer.pixels
        if px.shape[:2] != (h, w):
            raise ValueError(f"layer {layer.name!r} is {px.shape[1]}x{px.shape[0]}, "
                             f"the document {w}x{h}")
        if px.shape[2] == 4:
            chans = [(-1, px[..., 3]), (0, px[..., 0]), (1, px[..., 1]), (2, px[..., 2])]
        else:
            chans = [(-1, np.full((h, w), MAX, np.uint16)),
                     (0, px[..., 0]), (1, px[..., 1]), (2, px[..., 2])]
        enc = [(cid, _encode(p, ZIP_PREDICTION)) for cid, p in chans]
        rec = struct.pack(">4iH", 0, 0, h, w, len(enc))
        rec += b"".join(struct.pack(">hI", cid, 2 + len(d)) for cid, d in enc)
        flags = 0x08 | (0 if layer.visible else 0x02)     # 0x02 set = hidden
        rec += b"8BIM" + layer.blend + struct.pack(">BBBx", 255, 0, flags)
        ranges = b"\x00\x00\xff\xff" * 2 * (1 + nch)        # default blend-if ranges
        u = layer.name.encode("utf-16-be")
        extra = (struct.pack(">I", 0)                        # no layer mask
                 + struct.pack(">I", len(ranges)) + ranges
                 + _pascal(layer.name, 4)
                 + _tagged(b"luni", struct.pack(">I", len(u) // 2) + u))
        records.append(rec + struct.pack(">I", len(extra)) + extra)
        for _, d in enc:
            chandata += [struct.pack(">H", ZIP_PREDICTION), d]

    # A negative count says that the composite's extra channel is its transparency.
    head = struct.pack(">h", -len(layers)) + b"".join(records)
    body_len = len(head) + sum(len(c) for c in chandata)
    pad = -body_len % 4
    res = _resources(icc)

    with open(path, "wb") as f:
        f.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, nch, h, w, 16, 3))  # RGB
        f.write(struct.pack(">I", 0))                                      # colour mode data
        f.write(struct.pack(">I", len(res)) + res)
        f.write(struct.pack(">I", 4 + body_len + pad + 4))                # layer and mask info
        f.write(struct.pack(">I", body_len + pad))                        # layer info
        f.write(head)
        for c in chandata:
            f.write(c)
        f.write(b"\0" * pad)
        f.write(struct.pack(">I", 0))                                      # global layer mask
        if composite_rle:
            f.write(struct.pack(">H", RLE))
            f.write(_rle_planes([composite[..., c] for c in range(nch)]))
        else:
            f.write(struct.pack(">H", RAW))
            for c in range(nch):
                f.write(composite[..., c].astype(">u2").tobytes())


def read_summary(path):
    """Header and layer records of a PSD written by write(), for a quick check.

    Returns {"width", "height", "depth", "channels", "layers": [(name, visible, blend)]}.
    Reads only the headers, not the pixel data.
    """
    with open(path, "rb") as f:
        sig, version, channels, height, width, depth, mode = struct.unpack(">4sH6xHIIHH", f.read(26))
        if sig != b"8BPS" or version != 1:
            raise ValueError("not a PSD file")
        f.seek(struct.unpack(">I", f.read(4))[0], 1)                       # colour mode data
        f.seek(struct.unpack(">I", f.read(4))[0], 1)                       # image resources
        f.read(4)                                                          # layer and mask info length
        f.read(4)                                                          # layer info length
        count = abs(struct.unpack(">h", f.read(2))[0])
        layers = []
        for _ in range(count):
            f.read(16)
            nch = struct.unpack(">H", f.read(2))[0]
            f.read(6 * nch)
            sig, blend, _opacity, _clip, flags = struct.unpack(">4s4sBBBx", f.read(12))
            if sig != b"8BIM":
                raise ValueError("bad layer record")
            extra_len = struct.unpack(">I", f.read(4))[0]
            extra = f.read(extra_len)
            mask_len = struct.unpack(">I", extra[:4])[0]
            pos = 4 + mask_len
            ranges_len = struct.unpack(">I", extra[pos:pos + 4])[0]
            pos += 4 + ranges_len
            name = extra[pos + 1:pos + 1 + extra[pos]].decode("ascii", "replace")
            layers.append((name, not flags & 0x02, blend.decode("ascii")))
    return {"width": width, "height": height, "depth": depth, "mode": mode,
            "channels": channels, "layers": layers}
