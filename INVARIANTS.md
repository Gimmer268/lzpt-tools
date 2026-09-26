# The invariants an LZPT image has to satisfy

Two rules decide whether a repacked LZPT (`TPZL`) image is bootable. The first
one is enforced by the camera and getting it wrong bricks the body; the second
one is not enforced by anything, but it is what makes an interrupted flash
survivable. Both were measured on real firmware (ILCE-7RM2 / ILCE-6300) and are
checked by `lzpt.py check` / `lzpt_inplace.py`.

## 1. Every block offset and size must be a multiple of 512

The camera's NAND driver refuses to read a compressed block that does not start
on a 512-byte boundary:

```
[LDEC WARN]Offset for lded_read should be 0, current = 32, please check img
[ERR] LDEC request error : -1 (retry)
[LDEC ERR]mumin_devif_wait_trans : -10004
UDM: bdev_transfer() Line 183: read error: err = -1, pos = 17946112, size = 16384, xferred = 0
```

That is `kmod/nand.ko` (`mumin_lzp.c`) masking the offset with `0x1FF` and
failing the read. `/system` (`nflasha3`) then cannot be mounted, `init` never
reaches USB, and the camera cannot be recovered by flashing — only by reading
and writing the flash chip directly.

Measured, for the container that bricked an ILCE-7RM2:

```
bricked container : 418 blocks, offsets % 512 = {0: 127, 32: 291}, sizes % 512 = {0: 416, 32: 1, 272: 1}
the failing read  : pos = 17946112 = block 273, whose container offset is 9730080; 9730080 % 512 = 32
stock Sony images : 0 of 418 (nflasha3), 0 of 99 (nflasha7), 0 of 2757 (A6300 nflasha15) …
```

### Decoding cannot catch it

`fwtool`'s decoder reads blocks at whatever offset the table says, so a
misaligned container round-trips byte-perfectly in software and still kills the
camera. **Only an explicit check catches it.** A patch that adds one to
`fwtool.py` is in the works (`check_lzpt` subcommand + a refusal inside `pack`).

## 2. Keep the block table and the total size identical to the stock image

Not enforced by the camera, but it decides what happens when a write is
interrupted (power loss, cable pulled). If the new container has the *same*
block table and the same total size as the one already on flash, then at every
moment during the write the image on flash is a valid container: each block
either still holds the old bytes or holds the new ones, and both are
512-aligned LZ streams. The table itself is byte-identical, so rewriting it is a
no-op.

If the table changed, the map on flash and the data on flash disagree the moment
the table is written, and an interrupted write can leave an image the driver
cannot make sense of.

`lzpt_inplace.py` exists for exactly this: it recompresses only the 64 KiB
blocks that a patch touches, pads them back to their original size, and leaves
the table, the header and the total size untouched:

```console
$ python lzpt_inplace.py patch nflasha3 nflasha3.fsimg "<old string>" "<new string>" --out out.bin
```

Verify with a reference image (`-r` in the planned `fwtool.py check_lzpt`, or
`lzpt.py check` plus a table comparison).

## 3. The same 512 rule applies to WBI images

`nflasha5` is not a `TPZL` container but a `WBI1` image, and it has the same
kind of requirement: its sections are concatenated **with no padding between
them**, so every section's compressed size has to be padded to a multiple of 512
or every following section shifts off the grid.

```
ILCE-7RM2  WBI1: 1531 sections, sectorSize 512, data at 0x40000, table at 0x3120600
                 sum(size) == header dataSize, sum(osize) == header oDataSize,
                 sections with size % 512 != 0: 0
ILCE-6300  WBI1: 1635 sections, same checks, 0 unaligned
```

The checked invariants are: `sectorSize == 512`; the data base is 512-aligned;
every section's compressed size (and decompressed size) is a multiple of 512;
`sum(compressed) == dataSize`; `sum(decompressed) == oDataSize`; and
`file size == base + dataSize + 32 * numSections`.

## What is *not* an invariant (don't assert these)

* **The last block's `offset + size` does not equal the file size.** In Sony's
  own images it is *larger* (the last block is padded to 512, the file is not):
  `nflasha3` ends at 12,778,496 while the file is 12,778,256 bytes;
  `nflasha7` ends at 3,344,384 while the file is 3,344,144.
* **The gap between the table and the first block is not constant**
  (216 bytes in `nflasha3`, 208 in `nflasha7`).
* The 8 reserved bytes at `0x10..0x17` are zero in every image seen so far, but
  that is an observation, not a rule the driver enforces.

## Sony's own packages always satisfy rule 1

Consumer update packages (ILCE-7RM2 4.01, ILCE-6300 2.01) contain only
512-aligned `TPZL` members, and they never contain `loader` / `updater` /
`front` partitions. A repacked image that fails rule 1 is, by construction, not
Sony-like — which is exactly why the check is worth running before flashing.
