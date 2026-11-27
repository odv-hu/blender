"""Probe for #24: do the previews and the image editor read an RLE composite?

Writes two PSDs with odv_tools' own writer (blender/post_output/psd.py) from the
synthetic data of psd_probe.py, 3120 x 2080, 16-bit, layers beauty and matid:

    odv_rle_probe_raw.psd   merged composite uncompressed (as up to 0.0.7)
    odv_rle_probe_rle.psd   merged composite RLE (PackBits), as written now

What to check: the Windows Explorer preview and the macOS Finder preview show the
image (no olive noise), and the image editor opens both the same way.

    python3 tests/psd_rle_probe.py <output folder>
    blender --factory-startup -b --python tests/psd_rle_probe.py -- <output folder>

Needs only numpy. Prints each file's size and write time.
"""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psd_probe  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "odv_psd", os.path.join(HERE, "..", "blender", "post_output", "psd.py"))
psd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(psd)


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    out = args[0]
    os.makedirs(out, exist_ok=True)
    beauty, matid = psd_probe.synthetic()
    layers = [psd.Layer("beauty", beauty, True, b"norm"), psd.Layer("matid", matid[..., :3], False, b"norm")]
    composite = psd.flatten_over_white(beauty)
    print(f"{'file':26} {'MB':>8} {'s':>6}")
    for name, rle in (("raw", False), ("rle", True)):
        path = os.path.join(out, f"odv_rle_probe_{name}.psd")
        t = time.perf_counter()
        psd.write(path, layers, composite, composite_rle=rle)
        print(f"{os.path.basename(path):26} {os.path.getsize(path) / 1e6:8.1f} {time.perf_counter() - t:6.1f}")


if __name__ == "__main__":
    main()
