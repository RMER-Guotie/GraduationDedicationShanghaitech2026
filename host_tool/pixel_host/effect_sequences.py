"""Generate simple 32x48 RGB effect sequences for bench playback."""

from __future__ import annotations

from collections.abc import Iterator
import colorsys
import math

from .display_mapping import SCREEN_HEIGHT, SCREEN_WIDTH, clamp_byte, split_screen_to_boards
from .pixelbin import DEFAULT_BOARD_COUNT

RGB = tuple[int, int, int]


def iter_effect_frames(
    effect: str,
    frame_count: int,
    fps: int = 60,
    board_count: int = DEFAULT_BOARD_COUNT,
    rgb: RGB = (255, 0, 0),
    speed: float = 1.0,
    direction: str = "x",
    ww: int = 0,
    cw: int = 0,
) -> Iterator[tuple[int, int, tuple[bytes, ...]]]:
    """Yield pixelbin-compatible frame records for one generated effect."""
    if frame_count < 1:
        raise ValueError("frame_count must be positive")
    if fps < 1:
        raise ValueError("fps must be positive")

    for frame_index in range(frame_count):
        screen = render_screen_frame(effect, frame_index, frame_count, fps, board_count, rgb, speed, direction)
        yield ww, cw, split_screen_to_boards(screen, board_count=board_count)


def render_screen_frame(
    effect: str,
    frame_index: int,
    frame_count: int,
    fps: int,
    board_count: int,
    rgb: RGB,
    speed: float,
    direction: str,
) -> bytes:
    """Render one row-major logical screen frame."""
    if effect == "solid":
        return _solid(rgb, board_count)
    if effect == "columns":
        return _columns(frame_index, frame_count, board_count)
    if effect == "boards":
        return _boards(board_count)
    if effect == "moving_bar":
        return _moving_bar(frame_index, fps, board_count, rgb, speed, direction)
    if effect == "breath":
        return _breath(frame_index, frame_count, board_count, rgb)
    if effect == "rainbow":
        return _rainbow(frame_index, fps, board_count, speed, direction)
    if effect == "checker":
        return _checker(frame_index, fps, board_count, rgb, speed)
    if effect == "power_stress":
        return _power_stress(frame_index, fps, board_count, speed)
    raise ValueError(f"unknown effect {effect}")


def _solid(rgb: RGB, board_count: int) -> bytes:
    return bytes(_pixel_bytes(rgb) * (board_count * 8 * SCREEN_HEIGHT))


def _columns(frame_index: int, frame_count: int, board_count: int) -> bytes:
    width = board_count * 8
    active_x = min(width - 1, (frame_index * width) // max(1, frame_count))
    colors = _palette()
    data = bytearray()
    for _y in range(SCREEN_HEIGHT):
        for x in range(width):
            data.extend(_pixel_bytes(colors[x % len(colors)] if x == active_x else (0, 0, 0)))
    return bytes(data)


def _boards(board_count: int) -> bytes:
    colors = _palette()
    data = bytearray()
    for _y in range(SCREEN_HEIGHT):
        for x in range(board_count * 8):
            board = x // 8
            data.extend(_pixel_bytes(colors[board % len(colors)]))
    return bytes(data)


def _moving_bar(frame_index: int, fps: int, board_count: int, rgb: RGB, speed: float, direction: str) -> bytes:
    width = board_count * 8
    axis_len = width if direction == "x" else SCREEN_HEIGHT
    center = int((frame_index * max(0.1, speed)) % axis_len)
    bar_width = max(2, axis_len // 8)
    data = bytearray()
    for y in range(SCREEN_HEIGHT):
        for x in range(width):
            coord = x if direction == "x" else y
            dist = min((coord - center) % axis_len, (center - coord) % axis_len)
            level = max(0.0, 1.0 - dist / bar_width)
            data.extend(_scale_rgb(rgb, level))
    return bytes(data)


def _breath(frame_index: int, frame_count: int, board_count: int, rgb: RGB) -> bytes:
    phase = (frame_index / max(1, frame_count)) * math.tau
    level = 0.5 - 0.5 * math.cos(phase)
    return bytes(_scale_rgb(rgb, level) * (board_count * 8 * SCREEN_HEIGHT))


def _rainbow(frame_index: int, fps: int, board_count: int, speed: float, direction: str) -> bytes:
    width = board_count * 8
    t = frame_index * max(0.0, speed) / max(1, fps)
    data = bytearray()
    for y in range(SCREEN_HEIGHT):
        for x in range(width):
            coord = x / max(1, width - 1) if direction == "x" else y / max(1, SCREEN_HEIGHT - 1)
            hue = (coord + t * 0.25) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            data.extend((clamp_byte(r * 255), clamp_byte(g * 255), clamp_byte(b * 255)))
    return bytes(data)


def _checker(frame_index: int, fps: int, board_count: int, rgb: RGB, speed: float) -> bytes:
    width = board_count * 8
    phase = int(frame_index * max(0.1, speed) / max(1, fps / 4)) & 1
    data = bytearray()
    for y in range(SCREEN_HEIGHT):
        for x in range(width):
            enabled = (((x // 2) + (y // 2) + phase) & 1) == 0
            data.extend(_pixel_bytes(rgb if enabled else (0, 0, 0)))
    return bytes(data)


def _power_stress(frame_index: int, fps: int, board_count: int, speed: float) -> bytes:
    phase = int(frame_index * max(0.1, speed) / max(1, fps / 2)) & 1
    rgb = (255, 255, 255) if phase == 0 else (0, 0, 0)
    return _solid(rgb, board_count)


def _pixel_bytes(rgb: RGB) -> bytes:
    return bytes((clamp_byte(rgb[0]), clamp_byte(rgb[1]), clamp_byte(rgb[2])))


def _scale_rgb(rgb: RGB, level: float) -> bytes:
    return bytes((clamp_byte(rgb[0] * level), clamp_byte(rgb[1] * level), clamp_byte(rgb[2] * level)))


def _palette() -> list[RGB]:
    return [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        (255, 80, 0),
        (255, 255, 255),
    ]
