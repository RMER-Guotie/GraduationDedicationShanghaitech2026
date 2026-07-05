# Pixel Controller Host Tool

First-stage Python host tools for the firmware USB CDC/UART protocol.

## Setup

```powershell
cd host_tool
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## CLI Usage

Run commands from the `host_tool` directory:

```powershell
python -m tools.scan_devices
python -m tools.status COM5
python -m tools.all_black COM5
python -m tools.send_solid COM5 --rgb 255 0 0 --ww 0 --cw 0
python -m tools.send_solid COM5 --rgb 0 255 0 --chunk-delay-ms 5
```

Default serial settings are `115200 8N1`. USB CDC ignores the physical baud
rate, but this value works reliably with the current Windows CDC driver.
Full-frame writes are paced by default with a 2 ms delay after `FRAME_BEGIN` and
each RGB chunk so the current 256-byte downstream RX ring is not overrun during
bring-up.

## GUI Usage

Run the debug GUI from the `host_tool` directory:

```powershell
python -m tools.gui
```

The first GUI version supports port scanning, connect/disconnect, HELLO, STATUS,
ALL_BLACK, solid RGB output, and an 8-lane color test frame.

## Protocol Summary

The host sends framed packets:

```text
sync0 sync1 version type seq payload_len flags payload crc16
```

- sync: `0x5A 0xA5`
- version: `1`
- multi-byte fields: little-endian
- CRC: CRC16-CCITT-FALSE over `version..payload`

One full controller protocol frame is `8 * 48 * 3 = 1152` RGB bytes. Firmware
duplicates each logical pixel to the two physical LEDs on the same small board.
It is sent as:

```text
FRAME_BEGIN
8 * FRAME_RGB_CHUNK
FRAME_COMMIT
```

Each chunk contains 48 RGB pixels, or 144 bytes. Chunk mapping is lane-major:
chunk 0 is lane 0 logical pixels 0..47, chunk 1 is lane 1, and so on.

## Device Identity

The firmware currently reports `uid_hash` in `HELLO_RSP`. The future GUI will map
`uid_hash -> role` using `config/devices.example.json` as the starting format.
