"""Local frame file format for multi-board playback."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import BinaryIO, Iterable, Iterator

from . import protocol as proto

MAGIC = b"PXLBIN1\0"
VERSION = 1
DEFAULT_BOARD_COUNT = 4
HEADER_FORMAT = "<8sHHHHHHI32s"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


@dataclass(frozen=True)
class PixelBinHeader:
    """Validated metadata stored at the start of a pixelbin file."""

    version: int
    board_count: int
    lanes: int
    leds_per_lane: int
    fps: int
    flags: int
    frame_count: int

    @property
    def board_rgb_bytes(self) -> int:
        return self.lanes * self.leds_per_lane * 3

    @property
    def frame_rgb_bytes(self) -> int:
        return self.board_count * self.board_rgb_bytes

    @property
    def frame_bytes(self) -> int:
        return 4 + self.frame_rgb_bytes


@dataclass(frozen=True)
class PixelFrame:
    """One host playback frame with global white levels and board RGB slices."""

    index: int
    ww: int
    cw: int
    board_frames: tuple[bytes, ...]


class PixelBinReader:
    """Reader for board-major frame files used by the playback CLI."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._file: BinaryIO = open(path, "rb")
        self.header = read_header(self._file)
        self._next_index = 0

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "PixelBinReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def seek_frame(self, index: int) -> None:
        if not 0 <= index < self.header.frame_count:
            raise IndexError(f"frame index out of range: {index}")
        self._file.seek(HEADER_SIZE + index * self.header.frame_bytes)
        self._next_index = index

    def read_frame(self) -> PixelFrame | None:
        if self._next_index >= self.header.frame_count:
            return None

        raw = self._file.read(self.header.frame_bytes)
        if len(raw) != self.header.frame_bytes:
            raise ValueError(f"truncated frame {self._next_index}")

        ww, cw = struct.unpack_from("<HH", raw, 0)
        offset = 4
        board_frames = []
        for _board in range(self.header.board_count):
            next_offset = offset + self.header.board_rgb_bytes
            board_frames.append(raw[offset:next_offset])
            offset = next_offset

        frame = PixelFrame(self._next_index, ww, cw, tuple(board_frames))
        self._next_index += 1
        return frame

    def iter_frames(self, loop: bool = False) -> Iterator[PixelFrame]:
        while True:
            frame = self.read_frame()
            if frame is not None:
                yield frame
                continue
            if not loop:
                break
            self.seek_frame(0)


def read_header(file_obj: BinaryIO) -> PixelBinHeader:
    raw = file_obj.read(HEADER_SIZE)
    if len(raw) != HEADER_SIZE:
        raise ValueError("pixelbin header is truncated")

    magic, version, board_count, lanes, leds_per_lane, fps, flags, frame_count, _reserved = struct.unpack(
        HEADER_FORMAT,
        raw,
    )
    if magic != MAGIC:
        raise ValueError("bad pixelbin magic")
    if version != VERSION:
        raise ValueError(f"unsupported pixelbin version {version}")
    if board_count < 1 or board_count > 8:
        raise ValueError(f"bad board_count {board_count}")
    if lanes != proto.LANES or leds_per_lane != proto.LEDS_PER_LANE:
        raise ValueError(f"geometry mismatch: {lanes}x{leds_per_lane}")
    if fps < 1:
        raise ValueError(f"bad fps {fps}")

    return PixelBinHeader(
        version=version,
        board_count=board_count,
        lanes=lanes,
        leds_per_lane=leds_per_lane,
        fps=fps,
        flags=flags,
        frame_count=frame_count,
    )


def write_pixelbin(
    path: str,
    frames: Iterable[tuple[int, int, Iterable[bytes]]],
    fps: int = 60,
    board_count: int = DEFAULT_BOARD_COUNT,
) -> int:
    """Write frames and return the number of frames stored."""
    board_rgb_bytes = proto.LANES * proto.LEDS_PER_LANE * 3
    records: list[bytes] = []

    for ww, cw, board_frames in frames:
        board_list = list(board_frames)
        if len(board_list) != board_count:
            raise ValueError(f"expected {board_count} board frames, got {len(board_list)}")

        record = bytearray(struct.pack("<HH", ww & 0xFFFF, cw & 0xFFFF))
        for board_frame in board_list:
            if len(board_frame) != board_rgb_bytes:
                raise ValueError(f"board frame must be {board_rgb_bytes} bytes")
            record.extend(board_frame)
        records.append(bytes(record))

    header = struct.pack(
        HEADER_FORMAT,
        MAGIC,
        VERSION,
        board_count,
        proto.LANES,
        proto.LEDS_PER_LANE,
        fps,
        0,
        len(records),
        bytes(32),
    )

    with open(path, "wb") as file_obj:
        file_obj.write(header)
        for record in records:
            file_obj.write(record)

    return len(records)
