# Verification log

Date: 2026-09-26 · Windows, Python 3.12.14, standard library only.
Reference implementation used for cross-checking: **ma1co/fwtool.py** (decoder only).

## 1. Synthetic data (no Sony files needed)

```
$ python tests/test_lzpt.py
== round-trip / alignment ==
  ok zeros-1block     image    65536 B -> container     3072 B  (0.05x)  1 blocks
  ok zeros-3block     image   196608 B -> container     8192 B  (0.04x)  3 blocks
  ok text             image    65536 B -> container     3072 B  (0.05x)  1 blocks
  ok random-1block    image    65536 B -> container    66560 B  (1.02x)  1 blocks
  ok random-2block    image   131072 B -> container   132608 B  (1.01x)  2 blocks
  ok repetitive       image    65536 B -> container     3072 B  (0.05x)  1 blocks
  ok mixed            image   131072 B -> container     9728 B  (0.07x)  2 blocks
round-trip: 7 cases passed
== alignment detection ==
alignment check: broken offset detected as expected
== in-place patching ==
in-place patch: size unchanged, only the target bytes differ
== input validation ==
non-block-aligned images are rejected with a clear error

all tests passed
```

## 2. Real Sony firmware

Run with `tools/verify_against_sony.py <container> <unpacked image> --fwtool <path to fwtool.py>`.

```
### ILCE-7RM2 (CXD90014) nflasha3
stock container : nflasha3 (12778256 bytes)
unpacked image  : nflasha3_unpacked (27394048 bytes)
header          : blockSizeLog=16, tocOffset=24, tocSize=3344, blocks=418
stock alignment : offsets+0 / sizes+0 unaligned
1) our decoder  : matches fwtool's extraction (27394048 bytes, 1.3s)
2) our encoder  : 11951616 bytes in 18.1s (stock 12778256, ratio 0.935)
   alignment    : offsets+0 / sizes+0 unaligned
   round-trip   : byte-identical to the original image (1.4s)
3) fwtool.py    : decodes our container to the same image (independent decoder)
RESULT: OK

### ILCE-6300 (CXD90014) nflasha3
stock container : nflasha3 (12847376 bytes)
unpacked image  : nflasha3_unpacked (27459584 bytes)
header          : blockSizeLog=16, tocOffset=24, tocSize=3352, blocks=419
stock alignment : offsets+0 / sizes+0 unaligned
1) our decoder  : matches fwtool's extraction (27459584 bytes, 1.3s)
2) our encoder  : 12013056 bytes in 18.4s (stock 12847376, ratio 0.935)
   alignment    : offsets+0 / sizes+0 unaligned
   round-trip   : byte-identical to the original image (1.4s)
3) fwtool.py    : decodes our container to the same image (independent decoder)
RESULT: OK

### ILCE-6300 (CXD90014) nflasha7
stock container : nflasha7 (3348611 bytes)
unpacked image  : nflasha7_unpacked (6488064 bytes)
header          : blockSizeLog=16, tocOffset=24, tocSize=792, blocks=99
stock alignment : offsets+0 / sizes+0 unaligned
1) our decoder  : matches fwtool's extraction (6488064 bytes, 0.3s)
2) our encoder  : 3129856 bytes in 5.4s (stock 3348611, ratio 0.935)
   alignment    : offsets+0 / sizes+0 unaligned
   round-trip   : byte-identical to the original image (0.4s)
3) fwtool.py    : decodes our container to the same image (independent decoder)
RESULT: OK
```

## 3. What each result establishes

1. **Our decoder agrees with fwtool.py byte for byte** on stock images — the format
   understanding is not off, which matters because the in-place editor and the
   literal/reference analysis are built on top of it.
2. **An independent decoder reads our containers back to the identical image** —
   the encoder emits valid LZPT streams, not something only its own decoder accepts.
3. **Sony's own images have every block offset and size 512-aligned**
   (418/419/99 out of 419/420/100 entries), and so do ours. That is the invariant the
   camera enforces; the first repack we ever flashed was off by exactly 32 bytes here.

## 4. Not verified

* **Camera side.** No container produced by this code has been written to a camera
  yet — the unit that would have tested it was bricked by the pre-fix encoder and is
  awaiting repair. What is proven here is the *format*, not that the camera boots.
* The 128 KiB block variant (`blockSizeLog=17`, mentioned in the nex-hack wiki as
  version 0x11 for the EA50/FS700) has no sample to test against.
* The encoder's compression ratio was never tuned: it reaches 0.935x of Sony's own
  container size on real images, which is incidental, not a goal.
