"""Minimal writer for layered 16-bit RGB PSD files (#21).

Writes only what odv tools needs: full-canvas raster layers with a name,
visibility and blend mode, 16-bit RGB with a transparency channel, and the
merged composite. Uses only numpy and the Python standard library.

Layout, checked in the image editor on Windows (#21):
- layer channels ZIP-compressed with prediction, layer info in the standard
  layer section;
- the merged composite uncompressed, because the PSD thumbnail handler on
  Windows does not decode a ZIP composite. Its colour is flattened over white,
  as the format expects.
"""

import struct
import zlib
from collections import namedtuple

import numpy as np

MAX = 65535
RAW, ZIP, ZIP_PREDICTION = 0, 2, 3
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


def write(path, layers, composite, icc=None):
    """Write a layered 16-bit RGB PSD.

    layers: bottom first. composite: (H, W, 4) uint16, the merged result with
    its colour flattened over white (see flatten_over_white). icc: optional
    ICC profile bytes, embedded as the document's colour profile.
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
