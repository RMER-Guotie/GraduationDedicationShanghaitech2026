# Pixel Controller Host Protocol

This document describes the first implemented USB/UART host protocol.

## Transport

- USB CDC and UART use the same packet format.
- USB CDC RX callback only copies bytes into the shared firmware RX ring.
- UART RX uses USART1 RX DMA1 Channel5 in circular mode.
- UART baud is set at runtime to `921600`.
- UART TX is blocking for small responses only; UART TX DMA is not used.
- The board assumes only one physical link is active at a time.

## Packet Format

All multi-byte fields are little-endian.

```text
sync0        1 byte   0x5A
sync1        1 byte   0xA5
version      1 byte   currently 1
type         1 byte
seq          2 bytes
payload_len  2 bytes
flags        1 byte
payload      N bytes
crc16        2 bytes
```

`crc16` is CRC16-CCITT-FALSE over `version..payload`.

## Message Types

```text
0x01 HELLO_REQ
0x81 HELLO_RSP
0x10 FRAME_BEGIN
0x11 FRAME_RGB_CHUNK
0x12 FRAME_COMMIT
0x13 ALL_BLACK
0x20 STATUS_REQ
0xA0 STATUS_RSP
0xE0 ERROR_RSP
```

## Frame Transfer

One controller owns `8 x 96` RGB LEDs. A full RGB frame is `2304 bytes`.

Each RGB chunk carries `48` RGB pixels:

```text
chunk payload:
frame_id     2 bytes
chunk_index  1 byte   0..15
data_len     1 byte   must be 144
rgb_data   144 bytes  RGBRGB...
```

Chunk mapping is lane-major:

```text
chunk 0  -> lane 0, pixels 0..47
chunk 1  -> lane 0, pixels 48..95
chunk 2  -> lane 1, pixels 0..47
chunk 3  -> lane 1, pixels 48..95
...
chunk 14 -> lane 7, pixels 0..47
chunk 15 -> lane 7, pixels 48..95
```

`FRAME_BEGIN` payload:

```text
frame_id     2 bytes
chunk_count  1 byte   must be 16
frame_flags  1 byte
ww_level     2 bytes  0..1000
cw_level     2 bytes  0..1000
frame_crc32  4 bytes  reserved in first firmware version, may be 0
```

`FRAME_COMMIT` payload:

```text
frame_id     2 bytes
```

`FRAME_COMMIT` response uses message type `0x12`:

```text
frame_id       2 bytes
status         1 byte
received_mask  2 bytes
```

Commit succeeds only when all 16 chunks are received, frame ID matches, no severe
transaction error is active, and overcurrent protection is not active.

## Device Identity

`HELLO_RSP` payload:

```text
uid_hash          4 bytes
role_id           1 byte   0xFF means unknown
lanes             1 byte   8
leds_per_lane     2 bytes  96
chunk_rgb_bytes   2 bytes  144
chunk_count       1 byte   16
protocol_version  1 byte   1
max_payload       2 bytes  160
long_timeout_ms   2 bytes  10000
white_max_level   2 bytes  1000
```

The first firmware version derives identity from STM32 UID hash. The host should
not depend on COM port order.

## Status And Errors

`STATUS_RSP` payload:

```text
status_flags       2 bytes
active_link        1 byte   0 none, 1 USB, 2 UART
rc_stable_bits     1 byte
rx_used            2 bytes
frame_id           2 bytes
received_mask      2 bytes
packet_count       4 bytes
error_count        4 bytes
current_ma         4 bytes
ww_current         2 bytes
cw_current         2 bytes
uid_hash           4 bytes
commit_count       4 bytes
```

Status flag bits:

```text
bit0 overcurrent fault active
bit1 WS2812 pending_show active
bit2 host protocol owns output
bit3 frame transaction active
```

`ERROR_RSP` payload:

```text
error_code  1 byte
detail      2 bytes
```

Error codes:

```text
0  OK
1  bad protocol version
2  bad payload length
3  bad CRC16
4  bad message type
5  bad state
6  bad frame_id
7  bad chunk
8  incomplete frame
9  overcurrent fault active
10 RX overflow
```

## Output Rules

- `FRAME_COMMIT` applies RGB and WW/CW only after a valid full transaction.
- If WS2812 DMA is busy at commit, firmware sets `pending_show`; the latest
  committed frame is shown when DMA becomes idle.
- `ALL_BLACK` discards any active frame transaction, turns WW/CW off, and forces
  WS2812 black.
- If no valid protocol packet is received for `10000 ms` after host control
  starts, firmware outputs black.
- Overcurrent protection has priority over protocol output.
