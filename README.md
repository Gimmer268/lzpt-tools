# lzpt-tools

Encoder **and** in-place editor for Sony camera **LZPT** images — the piece that
was missing from every public tool.

An LZPT (magic `TPZL`) image is a flash-partition image split into 64 KiB
blocks, each compressed as one or more LZ77 streams. Sony ships several camera
partitions this way (`nflasha3` = the imaging side, `nflasha7`, `nflasha15`, …).

Existing public code can only *decode* them:

* `ma1co/fwtool.py` — decoder only ("`lz77` is a decompressor, there is no encoder")
* `unlzpt.c` (nex-hack / personal-view wiki) — decoder only
* `fwtool v07b12` (2014, nex-hack) — decoder only, and its own help says
  *"Further versions of fwtool will repack lower levels not implemented yet"*
  while its TODO list still reads *"v07: implement repacking of tar, lzpt"*

This project adds the encoder, and documents the one rule it has to obey.

## The rule: every block offset and size must be a multiple of 512

Rebuilding an image re-compresses blocks, which changes their offsets and
sizes. The camera's NAND driver refuses to read a compressed block that is not
512-byte aligned, and then the camera does not boot:

```
[LDEC WARN]Offset for lded_read should be 0, current = 32, please check img
[ERR] LDEC request error : -1 (retry)
[LDEC ERR]mumin_devif_wait_trans : -10004
UDM: bdev_transfer() Line 183: read error: err = -1, pos = 17946112, size = 16384, xferred = 0
```

That is the driver complaining about exactly the misalignment in the repacked
container. It is a bit test — from `kmod/nand.ko` (ARM, `mumin_lzp.c`), the
field is masked with `0x1FF` and reported if non-zero:

```asm
0x1e58  ldr   r2, [r2, sb]         ; the offset field
0x1e60  lsl   r5, r2, #0x17
0x1e68  lsr   r5, r5, #0x17        ; r5 = r2 & 0x1FF
0x1e70  cmp   r5, #0
0x1e80  beq   0x1ea8               ; zero -> carry on
0x1e84  ldr   r0, [pc, #0x638]     ; else print "Offset for lded_read should be 0, current = %d"
0x1e88  mov   r1, r5               ; %d = r2 & 0x1FF
```

Two consequences worth knowing:

* **Software round-trip tests do not catch this.** `fwtool`'s decoder accepts
  blocks at any offset, so a broken container can decode perfectly and still
  brick the camera. `lzpt.pack()` asserts the invariant instead.
* Sony's own images satisfy it everywhere: 418/418 blocks in the ILCE-7RM2
  `nflasha3`, 99/99 in the ILCE-6300 `nflasha7`.

## Usage

```console
$ python lzpt.py check  nflasha3
blocks            : 418 (block size 65536)
file size         : 12778256
unaligned offsets : 0
unaligned sizes   : 0
verdict           : aligned (accepts)

$ python lzpt.py unpack nflasha3 nflasha3.fsimg      # decode
$ python lzpt.py pack   nflasha3.fsimg out.bin --ref nflasha3   # encode
```

`pack` keeps the header reserved bytes (`0x10..0x17`) from `--ref`, pads every
block to 512 bytes, and refuses to return a container that is not 512-aligned or
that fails its own round-trip decode.

Editing without recompressing:

```console
$ python lzpt_inplace.py scan  nflasha3 nflasha3.fsimg 24
safe in-place patch targets (>=24 bytes, all literal, never referenced): 43
  0x01520b73 len= 46 b'#1 SMP PREEMPT RT Wed Feb 18 17:59:53 JST 2015'
  ...

$ python lzpt_inplace.py probe nflasha3 nflasha3.fsimg 0x1520b73 46
$ python lzpt_inplace.py patch nflasha3 nflasha3.fsimg "<old>" "<new>" --out out.bin
```

An output byte is either a *literal* (the byte sits in the stream, patchable) or
a *match* copy (not patchable), and patching a region that a later match read
from would propagate the change elsewhere. `lzpt_inplace.py` tracks both and
verifies that the patched container decodes to exactly the original image with
exactly the intended bytes changed — no recompression, container size and all
block offsets untouched, so the 512 rule cannot be violated.

## Verification

Full logs (synthetic tests and three real images): [VERIFICATION.md](VERIFICATION.md).
Summary on real firmware:

| image | blocks | our decoder vs fwtool | our encoder | alignment | round-trip | fwtool.py decodes ours |
|---|---|---|---|---|---|---|
| ILCE-7RM2 `nflasha3` | 418 | identical | 11,951,616 B (0.935× stock) | 0 unaligned | byte-identical | yes |
| ILCE-6300 `nflasha3` | 419 | identical | 12,013,056 B (0.935× stock) | 0 unaligned | byte-identical | yes |
| ILCE-6300 `nflasha7` | 99 | identical | 3,129,856 B (0.935× stock) | 0 unaligned | byte-identical | yes |

`tools/verify_against_sony.py` re-runs all of it, including the cross-check with
fwtool.py's independent decoder. `tests/test_lzpt.py` covers synthetic data
(zeros, text, random, repetitive, multi-block) with no Sony files needed.

## Appendix: the debug serial port

[SERIAL.md](SERIAL.md) records what was measured on the camera's MULTI terminal during the same
investigation: which contact carries the 115200 8N1 console, which are GND, and — just as
importantly — which ones were never identified. Short version: one contact is verified, the rest
is a voltage table, not an identification.

## Warning

This tool produces a *container*, not a flashable update package. Flashing
modified firmware can brick the camera, and a camera that fails before mounting
its root filesystem cannot be recovered over USB — it needs the flash chip to be
read and written directly. Keep a full NAND dump before you experiment.

## Credits

* [ma1co/fwtool.py](https://github.com/ma1co/fwtool.py) — the format was
  reverse-engineered from its decoder and its `lzpt.py` reader (MIT).
* nex-hack / [personal-view wiki](https://www.personal-view.com/faqs/sony-hack/lzpt)
  — the original LZPT description and `unlzpt.c`.
* The 512-byte invariant, the serial log above and the `nand.ko` disassembly
  come from a bricked ILCE-7RM2 and are documented here for the first time.

## License

MIT
