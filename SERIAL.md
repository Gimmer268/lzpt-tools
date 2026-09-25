# The MULTI terminal: measured notes

While chasing the boot failure described in the README I had to find the camera's debug
console, so I measured the MULTI terminal contact by contact. This is an appendix — a
different topic from the LZPT tools — but it is the same investigation, and almost nothing
about this port is written down publicly, so it seemed worth recording properly.

**Method:** camera powered on, multimeter black probe on the plug's metal shell (common with
the white wire), red probe on each contact. Numbering below is **left to right, looking at
the connector face** (the opposite direction from the public pinout doc referenced at the
bottom).

| contact (L→R) | idle voltage | status |
|---|---|---|
| 1 | 2.85 V | unidentified |
| 2 | 0.00 V | **GND** (common with the white wire and the shell) |
| 3 | 0.00 V | GND or a held-low signal – not fully confirmed |
| 4 | 3.10 V | unidentified |
| 5 | 2.90 V | unidentified |
| 6 | 2.85 V | unidentified |
| 7 | 3.10 V | unidentified (idle-high) |
| 8 | 3.13 V | **debug console TX** (verified, see below) |
| 9 | 3.13 V | unidentified (idle-high) |
| 10 | 3.13 V | **unidentified** (idle-high; previously mislabelled "3V3" in my notes) |

## Verified — two facts only

1. **Contact 8 is the debug console TX.** Connecting only GND + contact 8 to a USB-TTL adapter
   at **115200 8N1** produces readable kernel output. From a body that fails to boot, 635 bytes,
   byte-identical across three power cycles:

   ```
   [LDEC WARN]Offset for lded_read should be 0, current = 32, please check img
   [ERR] LDEC request error : -1 (retry)
   [LDEC ERR]mumin_devif_wait_trans : -10004
   UDM: bdev_transfer() Line 183: read error: err = -1, pos = 17946112, size = 16384, xferred = 0
   ```

   At 9600 8E1 that contact yields only `0x3F` noise, so the console is not the 9600 8E1 link.
2. **GND is contact 2** (and possibly 3): 0.00 V, electrically common with the plug's white wire
   and metal shell.

## Not verified — do not assume these

* **Every other contact is unidentified.** An idle-high reading is consistent with a supply, an
  idle UART line, or a pull-up; voltage alone does not distinguish them. In an earlier revision of
  my own notes I had written "contact 10 = 3V3" — that was an assumption from the reading, not a
  measurement, and it is withdrawn here.
* **The RX direction was never tested.** I only ever listened; I never drove a line into the
  camera, so I do not know which contact accepts input.
* Therefore this table is only good for one thing: a **read-only capture on GND + contact 8**.

## Open question about the public pinout

[`gyroflow/flowshutter` → `doc/sony-multi-terminal.md`](https://github.com/gyroflow/flowshutter/blob/master/doc/sony-multi-terminal.md)
is the only public pinout I could find. It numbers the contacts right-to-left and lists
`7: UART_TX`, `8: UART_RX`, `10: 3V3` with `9600 8E1`.

Under that numbering, its TX lands on the contact I measured at 3.10 V — plausible for an idle
TX — but its RX then lands on a 0.00 V contact. Read the other way, its TX position is off by one
from the contact that actually outputs the console. The most likely explanation is that the doc
describes the **remote/control** pair, which is not the same link as the 115200 8N1 debug console.
Probably worth pinning down, since anyone who follows that table for console access fails — which
is a plausible reason there is almost no public material about this port.

(I filed this as an issue on that repository; if the numbering gets settled, this file should be
updated to match.)

## Safety

* Read-only capture: **GND + contact 8, nothing else.**
* Do not connect the idle-high contacts. Whether any of them is a supply is unknown.
* The camera side is 3.3 V logic. If you ever drive a line into it, check your adapter's TX level
  first — some USB-TTL boards (including the CH340 writing cable I used for reading) can be 5 V.
