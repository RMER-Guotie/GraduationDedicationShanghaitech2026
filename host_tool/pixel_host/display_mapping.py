"""Map 32x48 logical screen frames to controller board frames."""

from __future__ import annotations

from collections.abc import Sequence

from . import protocol as proto
from .pixelbin import DEFAULT_BOARD_COUNT

SCREEN_WIDTH = DEFAULT_BOARD_COUNT * proto.LANES
SCREEN_HEIGHT = proto.LEDS_PER_LANE
SCREEN_RGB_BYTES = SCREEN_WIDTH * SCREEN_HEIGHT * 3


def split_screen_to_boards(screen_rgb: bytes, board_count: int = DEFAULT_BOARD_COUNT) -> tuple[bytes, ...]:
    """Split one 32x48 row-major RGB frame into board-major lane-major frames."""
    expected = board_count * proto.LANES * proto.LEDS_PER_LANE * 3
    if len(screen_rgb) != expected:
        raise ValueError(f"screen frame must be {expected} bytes")

    board_frames = [bytearray(proto.LANES * proto.LEDS_PER_LANE * 3) for _board in range(board_count)]
    width = board_count * proto.LANES

    for y in range(proto.LEDS_PER_LANE):
        row_offset = y * width * 3
        for x in range(width):
            board_index = x // proto.LANES
            lane = x % proto.LANES
            src_offset = row_offset + x * 3
            physical_pixel = proto.LEDS_PER_LANE - 1 - y
            dst_offset = (lane * proto.LEDS_PER_LANE + physical_pixel) * 3
            board_frames[board_index][dst_offset : dst_offset + 3] = screen_rgb[src_offset : src_offset + 3]

    return tuple(bytes(frame) for frame in board_frames)


def make_screen_from_pixels(rows: Sequence[Sequence[tuple[int, int, int]]]) -> bytes:
    """Pack rows[y][x] RGB tuples into row-major screen bytes."""
    if len(rows) != SCREEN_HEIGHT:
        raise ValueError(f"screen must have {SCREEN_HEIGHT} rows")

    data = bytearray()
    for row in rows:
        if len(row) != SCREEN_WIDTH:
            raise ValueError(f"screen rows must have {SCREEN_WIDTH} pixels")
        for r, g, b in row:
            data.extend((clamp_byte(r), clamp_byte(g), clamp_byte(b)))
    return bytes(data)


def clamp_byte(value: float | int) -> int:
    """Clamp numeric values to uint8 RGB range."""
    return max(0, min(255, int(round(value))))
