#!/usr/bin/env python3
"""Edit bytes inside an LZPT container **without recompressing**.

Why this exists: rebuilding a container re-compresses blocks, which changes
their offsets and sizes, and the camera's NAND driver requires both to be
multiples of 512 (see README.md).  Editing is unavoidable if you want to
change firmware content - but most edits can be done in place:

  * an output byte is either a *literal* (the byte sits in the stream) or the
    result of a *match* (copied from earlier output);
  * only literal bytes can be patched in place;
  * additionally the region must not be referenced by a later match, or the
    edit propagates into whatever copied it.

This tool decodes with source tracking, tells you whether a target range is
patchable, and verifies that the patched container decodes to exactly the
original image with exactly the intended bytes changed.

Usage
-----
  python lzpt_inplace.py scan  <container> <image.bin> [min_len] [limit]
  python lzpt_inplace.py probe <container> <image.bin> <offset> <length>
  python lzpt_inplace.py patch <container> <image.bin> "<old>" "<new>" \
         [--at 0xoffset] [--out patched_container.bin]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lzpt import LENS, parse_container  # noqa: E402


def decode_tracked(data):
    """Decode a container, also returning per-byte source and reference maps.

    literal[i] : offset in the container of the byte that produced output i,
                 or -1 if output i came from a match copy.
    refmap[i]  : 1 if output i was later read by a match (so patching it
                 would change more than one place).
    """
    block_log, toc, reserved = parse_container(data)
    target = 1 << block_log
    img = bytearray()
    literal = []
    refmap = bytearray()

    for index, (offset, size) in enumerate(toc):
        p = offset
        end = offset + size
        got = 0
        while got < target and p < end:
            kind = data[p]
            p += 1
            if kind == 0x0F:
                p += 1
                n = data[p] | (data[p + 1] << 8)
                p += 2
                img += data[p : p + n]
                refmap += bytearray(n)
                literal += list(range(p, p + n))
                p += n
                got += n
            elif kind == 0xF0:
                stream_done = False
                while not stream_done:
                    flags = data[p]
                    p += 1
                    if flags == 0:
                        img += data[p : p + 8]
                        refmap += bytearray(8)
                        literal += list(range(p, p + 8))
                        p += 8
                        got += 8
                        continue
                    for i in range(8):
                        if (flags >> i) & 1:
                            v = data[p] | (data[p + 1] << 8)
                            p += 2
                            length = LENS[(v & 0xFF) >> 4]
                            dist = ((v & 0x0F) << 8) | ((v >> 8) & 0xFF)
                            if dist == 0:
                                stream_done = True
                                break
                            src = len(img) - dist
                            before = len(img)
                            for j in range(src, min(before, src + length)):
                                refmap[j] = 1
                            img += (img[src:] * (length // dist + 1))[:length]
                            refmap += bytearray(length)
                            literal += [-1] * length
                            got += length
                        else:
                            img.append(data[p])
                            refmap.append(0)
                            literal.append(p)
                            p += 1
                            got += 1
            else:
                raise ValueError("unknown stream type 0x%02x at 0x%x" % (kind, p - 1))
        if got != target:
            raise ValueError("block %d decoded %d bytes, expected %d" % (index, got, target))

    return bytes(img), literal, refmap, reserved


def patch(container, literal, refmap, offset, new_bytes):
    out = bytearray(container)
    for i, byte in enumerate(new_bytes):
        out[literal[offset + i]] = byte
    return bytes(out)


def _report(data, image, offset, length, label=""):
    img, literal, refmap, _ = decode_tracked(data)
    if img != image:
        raise SystemExit("decoded image does not match the supplied image file")
    bad = [i for i in range(length) if literal[offset + i] < 0]
    refd = [i for i in range(length) if refmap[offset + i]]
    print("%srange 0x%x..0x%x (%d bytes)" % (label, offset, offset + length, length))
    print("  from match copies (cannot patch) : %d" % len(bad))
    print("  referenced by later matches      : %d" % len(refd))
    print("  verdict: %s" % (
        "patchable in place, zero propagation"
        if not bad and not refd
        else ("NOT patchable (match-sourced bytes)" if bad else "patchable but will propagate")
    ))
    return img, literal, refmap


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    mode = argv[1]
    data = open(argv[2], "rb").read()
    image = open(argv[3], "rb").read()

    if mode == "probe":
        offset, length = int(argv[4], 0), int(argv[5], 0)
        _report(data, image, offset, length)
        return 0

    if mode == "scan":
        min_len = int(argv[4], 0) if len(argv) > 4 else 24
        limit = int(argv[5], 0) if len(argv) > 5 else 25
        img, literal, refmap, _ = decode_tracked(data)
        if img != image:
            raise SystemExit("decoded image does not match the supplied image file")
        pat = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
        found = []
        for m in pat.finditer(img):
            s, e = m.start(), m.end()
            if all(literal[i] >= 0 for i in range(s, e)) and not any(refmap[i] for i in range(s, e)):
                found.append((s, e))
        print("safe in-place patch targets (>=%d bytes, all literal, never referenced): %d"
              % (min_len, len(found)))
        for s, e in found[:limit]:
            print("  0x%08x len=%3d %r" % (s, e - s, img[s : min(e, s + 70)]))
        return 0

    if mode == "patch":
        old, new = argv[4].encode(), argv[5].encode()
        if len(old) != len(new):
            raise SystemExit("old and new must have the same length (in-place editing)")
        if "--at" in argv:
            offset = int(argv[argv.index("--at") + 1], 0)
            if image[offset : offset + len(old)] != old:
                raise SystemExit("given offset does not contain the old string")
        else:
            offset = image.find(old)
            if offset < 0:
                raise SystemExit("old string not found")
            if image.find(old, offset + 1) >= 0:
                raise SystemExit("old string is not unique - use --at 0xoffset")
        img, literal, refmap = _report(data, image, offset, len(old), label="patch ")
        out = patch(data, literal, refmap, offset, new)
        if len(out) != len(data):
            raise SystemExit("container size changed - refusing")
        check_img, _, _, _ = decode_tracked(out)
        expected = bytearray(image)
        expected[offset : offset + len(new)] = new
        diff = [i for i in range(len(check_img)) if check_img[i] != expected[i]]
        print("re-decoded patched container: %d unexpected byte differences" % len(diff))
        if diff:
            print("  first few: %s" % [hex(i) for i in diff[:10]])
            return 3
        if "--out" in argv:
            dest = argv[argv.index("--out") + 1]
            open(dest, "wb").write(out)
            print("wrote %s (%d bytes, same size as the original container)" % (dest, len(out)))
        print("OK: only the requested bytes changed, container layout untouched")
        return 0

    print("unknown mode %r" % mode)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
