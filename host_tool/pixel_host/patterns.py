"""Simple frame generators for CLI testing."""

from __future__ import annotations

from .protocol import LANES, LEDS_PER_LANE, solid_frame_rgb


def solid(r: int, g: int, b: int) -> bytes:
    return solid_frame_rgb(r, g, b)


def lane_test() -> bytes:
    """Return a frame with a distinct color per lane."""
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        (255, 80, 0),
        (255, 255, 255),
    ]
    data = bytearray()
    for lane in range(LANES):
        r, g, b = colors[lane % len(colors)]
        data.extend(bytes((r, g, b)) * LEDS_PER_LANE)
    return bytes(data)
