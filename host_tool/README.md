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
```

Default serial settings are `921600 8N1`, matching the current firmware.

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

One full controller frame is `8 * 96 * 3 = 2304` RGB bytes. It is sent as:

```text
FRAME_BEGIN
16 * FRAME_RGB_CHUNK
FRAME_COMMIT
```

Each chunk contains 48 RGB pixels, or 144 bytes. Chunk mapping is lane-major:
chunk 0/1 are lane 0 pixels 0..47 / 48..95, chunk 2/3 are lane 1, and so on.

## Device Identity

The firmware currently reports `uid_hash` in `HELLO_RSP`. The future GUI will map
`uid_hash -> role` using `config/devices.example.json` as the starting format.
