# Pixel Controller Host Tool

First-stage Python host tools for the firmware USB CDC/UART protocol.

## Setup

```powershell
cd host_tool
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

For a new Windows PC, the same setup can be done with:

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\setup_host_env.ps1
.\.venv\Scripts\activate
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
Full-frame writes use no default chunk delay after the 2-chunk protocol and
1024-byte downstream RX ring were validated at about 60 fps.

## Multi-Board File Playback

Each controller reports a board role in `HELLO_RSP`. Set `APP_ROLE_ID` in
`Core/Inc/app_config.h` before flashing a board. Valid roles are physical PCB
numbers `1..20`. The playback config maps those physical numbers to file slots
`1..4`.

Create a local test file:

```powershell
python -m tools.generate_test_file --output test.pixelbin --pattern breath --frames 240 --fps 60
```

Scan connected boards:

```powershell
python -m tools.scan_devices
```

Play the file to all boards that answer HELLO:

```powershell
python -m tools.play_file --file test.pixelbin --config config/devices.json
```

The `.pixelbin` format stores frames in board-major order. Each frame contains
global `WW/CW` levels followed by four board slices. Each board slice is one
logical `8 * 48 * 3 = 1152` byte RGB frame. During playback each connected board
has its own sending thread. A device error skips that board's current frame and
does not stop other boards.

Example config for four physical boards selected from PCB IDs `1..20`:

```json
{
  "devices": [
    { "role_id": 7, "slot": 1, "name": "board_7", "enabled": true },
    { "role_id": 11, "slot": 2, "name": "board_11", "enabled": true },
    { "role_id": 13, "slot": 3, "name": "board_13", "enabled": true },
    { "role_id": 18, "slot": 4, "name": "board_18", "enabled": true }
  ]
}
```

## Windows Autoplay

Autoplay is intended for the installed display PC. It opens a console, scans USB
CDC devices, waits for four controller boards, and loops fixed local mode files.

Prepare the host environment once:

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\setup_host_env.ps1
```

Place the four mode files under `host_tool\autoplay\`:

```text
mode1.pixelbin
mode2.pixelbin
mode3.pixelbin
mode4.pixelbin
```

Run manually:

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\autoplay.ps1
```

Install Windows current-user startup:

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

Remove startup:

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1
```

Autoplay behavior:

- Scans visible COM ports and sends HELLO until four valid controllers are
  connected.
- Maps connected controllers by `role_id` ascending to slot 1..4.
- Polls `STATUS_RSP.rc_stable_bits` on connected boards while waiting and during
  playback.
- RC bit0..bit3 selects `mode1`..`mode4`.
- If any RC command appears before all four boards are connected, autoplay stops
  waiting for missing boards and starts with the connected subset.
- Missing or failed boards are logged in the console and skipped; other boards
  continue.

The first version uses the existing `STATUS_RSP.rc_stable_bits` field, so no
firmware protocol change is required. If the RC receiver outputs short pulses
that return to zero faster than the host polling interval, add a firmware
edge/event counter later.

## GUI Usage

Run the debug GUI from the `host_tool` directory:

```powershell
python -m tools.gui
```

The first GUI version supports port scanning, connect/disconnect, HELLO, STATUS,
ALL_BLACK, solid RGB output, and an 8-lane color test frame.

## Offline Video Generator

Run the offline generator GUI from the `host_tool` directory:

```powershell
python -m tools.generator_gui
```

The generator is not part of live playback. It is used occasionally to convert a
local video into a `.pixelbin` file, which can later be imported by the debug
GUI playback mode.

Generator behavior:

- Uses OpenCV to read common video files such as `mp4`, `avi`, `mov`, `mkv`, and
  `wmv`; uses Pillow to read animated `gif` input.
- Crops the source video from the center to the display aspect ratio `2:3`.
- Resizes each sampled frame to the logical display size `32 x 48`.
- Stores frames in the existing `.pixelbin` board-major format.
- Supports output FPS, start/end time, brightness, gamma, saturation, and fixed
  global `WW/CW` levels.
- Can also write an optional preview MP4. The preview is generated from the same
  processed `32 x 48` logical frames as the `.pixelbin`, then enlarged to
  `320 x 480` with nearest-neighbor scaling for visual checking.
- GIF input is converted once through its own timeline; it is not looped
  automatically during file generation.

Logical mapping for generated files:

```text
x = 0..31, left to right
y = 0..47, top to bottom in the source/video
board slot = x / 8 + 1
lane       = x % 8
pixel      = 47 - y
```

Each lane is physically wired from bottom to top. The logical source/video still
uses normal top-to-bottom rows, so the host flips `y` inside each lane before
writing board-major frame data. The current generator does not implement
serpentine wiring, per-board rotation, or geometric correction.

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
4 * FRAME_RGB_CHUNK
FRAME_COMMIT
```

Each chunk contains two complete logical lanes, or 288 RGB bytes. Chunk 0
contains lanes 0..1, chunk 1 contains lanes 2..3, chunk 2 contains lanes
4..5, and chunk 3 contains lanes 6..7.

## Device Identity

The firmware reports both `uid_hash` and `role_id` in `HELLO_RSP`. Role ID is
normally fixed by the board firmware macro. The host playback config maps that
physical role ID to a logical playback slot.
