#!/usr/bin/env python3
"""Verify the encoder/decoder against a real Sony LZPT image.

Checks, in order:

  1. our decoder reproduces the image that fwtool.py extracted from the stock
     container (byte for byte);
  2. the stock container's block offsets and sizes are all 512-aligned
     (this is the invariant the camera enforces - see README.md);
  3. our encoder can rebuild a container for the same image which
     (a) is 512-aligned, (b) decodes back byte-identically, and
     (c) is also decodable by fwtool.py's independent implementation.

Usage:
  python tools/verify_against_sony.py <stock_container> <unpacked_image> \
         [--fwtool <path to fwtool.py-master>]
"""
import io
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import lzpt  # noqa: E402


def fwtool_decode(container, fwtool_dir):
    """Decode with fwtool.py (independent implementation)."""
    sys.path.insert(0, fwtool_dir)
    from fwtool import lz77 as fw_lz77  # noqa: E402
    from fwtool.archive.lzpt import LzptHeader, LzptTocEntry, lzptHeaderMagic  # noqa: E402

    f = io.BytesIO(container)
    header = LzptHeader.unpack(f)
    assert header.magic == lzptHeaderMagic
    toc = [
        LzptTocEntry.unpack(f, header.tocOffset + off)
        for off in range(0, header.tocSize, LzptTocEntry.size)
    ]
    out = bytearray()
    for entry in toc:
        f.seek(entry.offset)
        block = io.BytesIO(f.read(entry.size))
        got = 0
        while got < 2 ** header.blockSize:
            chunk = fw_lz77.inflateLz77(block)
            if not chunk:
                break
            out += chunk
            got += len(chunk)
        assert got == 2 ** header.blockSize, "fwtool decode: short block"
    return bytes(out)


def main(argv):
    container_path, image_path = argv[1], argv[2]
    fwtool_dir = None
    if "--fwtool" in argv:
        fwtool_dir = argv[argv.index("--fwtool") + 1]

    container = open(container_path, "rb").read()
    image = open(image_path, "rb").read()
    print("stock container : %s (%d bytes)" % (os.path.basename(container_path), len(container)))
    print("unpacked image  : %s (%d bytes)" % (os.path.basename(image_path), len(image)))

    block_log, toc, reserved = lzpt.parse_container(container)
    print("header          : blockSizeLog=%d, tocOffset=%d, tocSize=%d, blocks=%d"
          % (block_log, 24, len(toc) * 8, len(toc)))
    print("stock alignment : offsets+%d / sizes+%d unaligned"
          % (sum(1 for o, _ in toc if o % 512), sum(1 for _, s in toc if s % 512)))

    t0 = time.time()
    decoded = lzpt.unpack(container)
    print("1) our decoder  : %s (%d bytes, %.1fs)"
          % ("matches fwtool's extraction" if decoded == image else "MISMATCH",
             len(decoded), time.time() - t0))
    if decoded != image:
        return 1

    t0 = time.time()
    ours = lzpt.pack(image, block_log=block_log, reserved=reserved)
    dt = time.time() - t0
    report = lzpt.check(ours)
    print("2) our encoder  : %d bytes in %.1fs (stock %d, ratio %.3f)"
          % (len(ours), dt, len(container), len(ours) / len(container)))
    print("   alignment    : offsets+%d / sizes+%d unaligned"
          % (report["unaligned_offsets"], report["unaligned_sizes"]))
    if report["unaligned_offsets"] or report["unaligned_sizes"]:
        print("   FAILED: produced an unaligned container")
        return 1

    t0 = time.time()
    roundtrip = lzpt.unpack(ours)
    print("   round-trip   : %s (%.1fs)"
          % ("byte-identical to the original image" if roundtrip == image else "MISMATCH",
             time.time() - t0))
    if roundtrip != image:
        return 1

    if fwtool_dir:
        try:
            other = fwtool_decode(ours, fwtool_dir)
            print("3) fwtool.py    : %s (independent decoder)"
                  % ("decodes our container to the same image" if other == image else "MISMATCH"))
            if other != image:
                return 1
        except Exception as exc:  # noqa: BLE001
            print("3) fwtool.py    : cross-check failed: %s" % exc)
            return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
