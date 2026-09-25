#!/usr/bin/env python3
"""LZPT (TPZL) image container: decoder *and* encoder.

Sony camera firmware ("second wave" / generation 3 and newer) ships some
flash partitions as LZPT images: a TOC of 64 KiB blocks, each block holding
one or more LZ77 streams.

Public tooling only ever *decoded* these images:

  * fwtool.py (ma1co)          - decoder only ("lz77 is a decompressor")
  * unlzpt.c (nex-hack wiki)   - decoder only
  * fwtool v07b12 (nex-hack)   - decoder only; its TODO list still says
                                 "v07: implement repacking of tar, lzpt"

This file is an encoder, written by reverse-engineering the decoders.
See README.md for the one hard constraint it has to satisfy.

Format
------
  header : 'TPZL' | u32 blockSizeLog (16 -> 64 KiB) | u32 tocOffset | u32 tocSize
  TOC    : per block, u32 offset + u32 size   (absolute file offsets, 512-aligned)
  block  : one or more LZ77 streams, decoded until 2**blockSizeLog bytes
  LZ77   : 0x0f = stored -> 1 skipped byte, u16 LE length, raw bytes
           0xf0 = packed -> loop { u8 flags; for bit i in 0..7:
                    bit set -> u8 hi, u8 lo:
                               len  = LENS[hi >> 4]
                               dist = ((hi & 0x0f) << 8) | lo
                               dist == 0 ends the stream,
                               else copy len bytes from out[-dist:]
                    bit clear -> one literal byte }

Command line
------------
  python lzpt.py check  <container>
  python lzpt.py unpack <container> <out.bin>
  python lzpt.py pack   <image.bin> <out.bin> [--ref <stock container>]
"""
import io
import os
import struct
import sys

__version__ = "1.0"

MAGIC = b"TPZL"
BLOCK_LOG_DEFAULT = 16
BLOCK_ALIGN = 512
LENS = list(range(3, 17)) + [32, 64]

# encoder tuning (LZ77 window is 12 bit in this format)
WINDOW = 4095
MAXLEN = 64
MAX_CANDIDATES = 48


# --------------------------------------------------------------------------
# decoder
# --------------------------------------------------------------------------
def inflate_lz77(f):
    """Decode one LZ77 stream from a file-like object."""
    first = f.read(1)
    if not first:
        return b""
    kind = first[0]
    if kind == 0x0F:
        f.read(1)
        n = struct.unpack("<H", f.read(2))[0]
        return f.read(n)
    if kind != 0xF0:
        raise ValueError("unknown stream type 0x%02x" % kind)

    out = bytearray()
    while True:
        flags = f.read(1)[0]
        if flags == 0:
            out += f.read(8)
            continue
        for i in range(8):
            if (flags >> i) & 1:
                d = f.read(2)
                if len(d) < 2:
                    return bytes(out)
                v = d[0] | (d[1] << 8)
                length = LENS[(v & 0xFF) >> 4]
                dist = ((v & 0x0F) << 8) | ((v >> 8) & 0xFF)
                if dist == 0:
                    return bytes(out)
                src = len(out) - dist
                out += (out[src:] * (length // dist + 1))[:length]
            else:
                b = f.read(1)
                if not b:
                    return bytes(out)
                out.append(b[0])


def parse_container(data):
    """Return (block_log, [(offset, size), ...], reserved8)."""
    if data[:4] != MAGIC:
        raise ValueError("not an LZPT container (bad magic %r)" % data[:4])
    block_log, toc_offset, toc_size = struct.unpack_from("<III", data, 4)
    toc = [
        struct.unpack_from("<II", data, toc_offset + i)
        for i in range(0, toc_size, 8)
    ]
    return block_log, toc, data[16:24]


def unpack(data, image_size=None):
    """Decode a whole container into the raw partition image.

    Every real Sony image is an exact multiple of the block size, so the
    default path requires each block to decode to the full block size.
    Pass `image_size` to decode a container whose last block is short.
    """
    block_log, toc, _ = parse_container(data)
    target = 1 << block_log
    out = bytearray()
    for index, (offset, size) in enumerate(toc):
        want = target
        if image_size is not None and index == len(toc) - 1:
            want = image_size - target * index
        block = io.BytesIO(data[offset : offset + size])
        got = 0
        while got < want:
            chunk = inflate_lz77(block)
            if not chunk:
                break
            out += chunk
            got += len(chunk)
        if got != want:
            raise ValueError(
                "block %d decoded %d bytes, expected %d (truncated or padded container?)"
                % (index, got, want)
            )
    return bytes(out)


def check(data):
    """Alignment report for a container."""
    block_log, toc, _ = parse_container(data)
    return {
        "block_log": block_log,
        "blocks": len(toc),
        "unaligned_offsets": sum(1 for o, _ in toc if o % BLOCK_ALIGN),
        "unaligned_sizes": sum(1 for _, s in toc if s % BLOCK_ALIGN),
        "first_offset": toc[0][0] if toc else 0,
        "size": len(data),
    }


# --------------------------------------------------------------------------
# encoder
# --------------------------------------------------------------------------
class _Matcher:
    def __init__(self, data):
        self.data = data
        self.n = len(data)
        self.pos = {}

    def add(self, i):
        if i + 3 <= self.n:
            key = self.data[i : i + 3]
            lst = self.pos.get(key)
            if lst is None:
                self.pos[key] = [i]
            else:
                lst.append(i)
                if len(lst) > 256:
                    del lst[:-128]

    def find(self, i):
        if i + 3 > self.n:
            return None
        data = self.data
        cands = self.pos.get(data[i : i + 3])
        if not cands:
            return None
        best = None
        checked = 0
        maxl = min(self.n - i, MAXLEN)
        for j in reversed(cands):
            if i - j > WINDOW:
                break
            checked += 1
            if checked > MAX_CANDIDATES:
                break
            length = 3
            while length < maxl and data[j + length] == data[i + length]:
                length += 1
            code = -1
            for ci, L in enumerate(LENS):
                if L <= length:
                    code = ci
                else:
                    break
            if code < 0:
                continue
            L = LENS[code]
            if best is None or L > best[1] or (L == best[1] and (i - j) < best[2]):
                best = (code, L, i - j)
            if L == MAXLEN:
                break
        return best


def deflate_lz77_packed(data):
    """Encode as one 0xf0 stream."""
    m = _Matcher(data)
    toks = []
    i = 0
    n = len(data)
    while i < n:
        hit = m.find(i)
        if hit is None:
            toks.append((False, data[i : i + 1]))
            m.add(i)
            i += 1
        else:
            code, length, dist = hit
            toks.append((True, bytes([(code << 4) | (dist >> 8), dist & 0xFF])))
            for k in range(i, min(i + length, n)):
                m.add(k)
            i += length
    toks.append((True, b"\x00\x00"))

    out = bytearray(b"\xf0")
    for g in range(0, len(toks), 8):
        flags = 0
        body = bytearray()
        for bi, (is_match, payload) in enumerate(toks[g : g + 8]):
            if is_match:
                flags |= 1 << bi
            body += payload
        out.append(flags)
        out += body
    return bytes(out)


def deflate_lz77_stored(data):
    """Encode as 0x0f stored runs (fallback for incompressible data)."""
    out = bytearray()
    off = 0
    while off < len(data):
        piece = data[off : off + 0xFFFF]
        out += b"\x0f\x00" + struct.pack("<H", len(piece)) + piece
        off += len(piece)
    return bytes(out)


def deflate_lz77(data):
    """Smallest of the two stream encodings."""
    packed = deflate_lz77_packed(data)
    stored = deflate_lz77_stored(data)
    return packed if len(packed) <= len(stored) else stored


def pack(image, block_log=BLOCK_LOG_DEFAULT, reserved=None, align=BLOCK_ALIGN, verify=True):
    """Build an LZPT container from a raw partition image.

    `align` is not optional in practice: the camera's NAND driver refuses a
    compressed block whose offset is not a multiple of 512 and then fails to
    boot.  See README.md.  The result is checked before being returned.
    """
    block = 1 << block_log
    if len(image) % block:
        raise ValueError(
            "image size %d is not a multiple of the block size %d - every real Sony "
            "image is block-aligned, and the container format has no length field, "
            "so a short last block cannot be represented safely" % (len(image), block)
        )
    encoded = []
    for start in range(0, len(image), block):
        chunk = deflate_lz77(image[start : start + block])
        if align and len(chunk) % align:
            chunk += b"\x00" * (align - len(chunk) % align)
        encoded.append(chunk)

    toc_offset = 24
    toc_size = 8 * len(encoded)
    data_start = (toc_offset + toc_size + (align - 1)) & ~(align - 1)

    head = bytearray(MAGIC)
    head += struct.pack("<III", block_log, toc_offset, toc_size)
    head += b"\x00" * (toc_offset - len(head))
    if reserved:
        head[16:24] = reserved

    toc = bytearray()
    body = bytearray()
    offset = data_start
    for chunk in encoded:
        toc += struct.pack("<II", offset, len(chunk))
        body += chunk
        offset += len(chunk)
    out = bytes(head) + bytes(toc) + b"\x00" * (data_start - toc_offset - toc_size) + bytes(body)

    if verify:
        report = check(out)
        if align and (report["unaligned_offsets"] or report["unaligned_sizes"]):
            raise AssertionError("internal error: produced an unaligned container")
        if unpack(out) != image:
            raise AssertionError("internal error: round-trip mismatch")
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    mode = argv[1]

    if mode == "check":
        data = open(argv[2], "rb").read()
        r = check(data)
        print("blocks            : %d (block size %d)" % (r["blocks"], 1 << r["block_log"]))
        print("file size         : %d" % r["size"])
        print("unaligned offsets : %d" % r["unaligned_offsets"])
        print("unaligned sizes   : %d" % r["unaligned_sizes"])
        print("verdict           : %s" % ("aligned (accepts)" if not (r["unaligned_offsets"] or r["unaligned_sizes"]) else "NOT aligned (camera will refuse)"))
        return 0

    if mode == "unpack":
        data = open(argv[2], "rb").read()
        image = unpack(data)
        open(argv[3], "wb").write(image)
        print("wrote %s (%d bytes)" % (argv[3], len(image)))
        return 0

    if mode == "pack":
        image = open(argv[2], "rb").read()
        reserved = None
        if "--ref" in argv:
            ref = open(argv[argv.index("--ref") + 1], "rb").read()
            reserved = ref[16:24]
        out = pack(image, reserved=reserved)
        open(argv[3], "wb").write(out)
        r = check(out)
        print("wrote %s (%d bytes, %d blocks)" % (argv[3], len(out), r["blocks"]))
        print("alignment: offsets+%d / sizes+%d unaligned, round-trip OK"
              % (r["unaligned_offsets"], r["unaligned_sizes"]))
        return 0

    print("unknown mode %r" % mode)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
