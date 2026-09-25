#!/usr/bin/env python3
"""Self-contained tests for the LZPT encoder/decoder (no Sony data needed).

Run:  python tests/test_lzpt.py
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import lzpt  # noqa: E402
import lzpt_inplace  # noqa: E402

BLOCK = 1 << lzpt.BLOCK_LOG_DEFAULT


def patterns():
    rnd = random.Random(0xC0DE)
    yield "zeros-1block", bytes(BLOCK)
    yield "zeros-3block", bytes(BLOCK * 3)
    yield "text", (b"the quick brown fox jumps over the lazy dog\n" * 3000)[: BLOCK]
    yield "random-1block", bytes(rnd.getrandbits(8) for _ in range(BLOCK))
    yield "random-2block", bytes(rnd.getrandbits(8) for _ in range(BLOCK * 2))
    yield "repetitive", (b"ABCD" * 16 + b"\x00" * 48 + b"\xff" * 16) * 512
    yield "mixed", (
        bytes(rnd.getrandbits(8) for _ in range(4096)) + bytes(BLOCK - 4096 + BLOCK)
    )


def test_roundtrip():
    n = 0
    for name, image in patterns():
        container = lzpt.pack(image)
        got = lzpt.unpack(container)
        assert got == image, "%s: round-trip mismatch (%d vs %d)" % (name, len(got), len(image))
        report = lzpt.check(container)
        assert report["unaligned_offsets"] == 0, name
        assert report["unaligned_sizes"] == 0, name
        assert container[:4] == b"TPZL"
        expected_blocks = (len(image) + BLOCK - 1) // BLOCK
        assert report["blocks"] == expected_blocks, "%s: %d blocks" % (name, report["blocks"])
        n += 1
        print(
            "  ok %-16s image %8d B -> container %8d B  (%.2fx)  %d blocks"
            % (name, len(image), len(container), len(container) / max(len(image), 1), report["blocks"])
        )
    print("round-trip: %d cases passed" % n)


def test_alignment_is_enforced():
    """A container whose blocks are not 512-aligned must be reported as such."""
    image = bytes(65536)
    container = bytearray(lzpt.pack(image))
    # break the first block's offset on purpose
    first_off = int.from_bytes(container[24:28], "little")
    container[24:28] = (first_off + 1).to_bytes(4, "little")
    report = lzpt.check(bytes(container))
    assert report["unaligned_offsets"] > 0, "check() failed to notice a broken offset"
    print("alignment check: broken offset detected as expected")


def test_inplace():
    """Patching literal bytes must change exactly those bytes."""
    rnd = random.Random(1234)
    # block 2 is high-entropy, so the target string ends up stored as literals
    blob = bytes(rnd.getrandbits(8) for _ in range(BLOCK))
    image = bytearray(bytes(BLOCK) + blob)
    target = b"PATCH-ME-PLEASE"
    image[BLOCK + 100 : BLOCK + 100 + len(target)] = target
    container = lzpt.pack(bytes(image))

    offset = image.find(target)
    assert offset >= 0
    img, literal, refmap, _ = lzpt_inplace.decode_tracked(container)
    assert img == bytes(image)
    bad = [i for i in range(len(target)) if literal[offset + i] < 0]
    assert not bad, "expected the target to be stored as literals"
    new = b"patched-ok" + b"!" * (len(target) - len(b"patched-ok"))
    assert len(new) == len(target)
    patched = lzpt_inplace.patch(container, literal, refmap, offset, new)
    assert len(patched) == len(container)
    result = lzpt.unpack(patched)
    expected = bytearray(image)
    expected[offset : offset + len(new)] = new
    assert result == bytes(expected), "in-place patch changed the wrong bytes"
    print("in-place patch: size unchanged, only the target bytes differ")


def test_unaligned_image_is_rejected():
    try:
        lzpt.pack(b"x")
    except ValueError as e:
        assert "not a multiple" in str(e)
        print("non-block-aligned images are rejected with a clear error")
        return
    raise AssertionError("pack() accepted an image that is not block-aligned")


if __name__ == "__main__":
    print("== round-trip / alignment ==")
    test_roundtrip()
    print("== alignment detection ==")
    test_alignment_is_enforced()
    print("== in-place patching ==")
    test_inplace()
    print("== input validation ==")
    test_unaligned_image_is_rejected()
    print("\nall tests passed")
