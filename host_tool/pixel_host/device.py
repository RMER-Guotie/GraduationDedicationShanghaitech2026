"""High-level device operations built on the wire protocol."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import time
from typing import Optional

from . import protocol as proto
from .protocol import CommitResponse, HelloResponse, StatusResponse
from .serial_link import SerialLink

PRECISE_SLEEP_THRESHOLD_S = 0.005
DEFAULT_CHUNK_DELAY_S = 0.0


@dataclass
class FrameTiming:
    """Host-side timing breakdown for the most recent full-frame transfer."""

    frame_id: int
    chunk_count: int = 0
    begin_ms: float = 0.0
    chunks_ms: float = 0.0
    pacing_ms: float = 0.0
    commit_write_ms: float = 0.0
    response_wait_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class PixelDevice:
    """Convenience API for one downstream controller board."""

    link: SerialLink
    response_timeout: float = 1.0
    last_frame_timing: Optional[FrameTiming] = None

    def __post_init__(self) -> None:
        self._seq_iter = itertools.count(1)
        self._frame_id_iter = itertools.count(1)

    def next_seq(self) -> int:
        return next(self._seq_iter) & 0xFFFF

    def next_frame_id(self) -> int:
        return next(self._frame_id_iter) & 0xFFFF

    def hello(self) -> HelloResponse:
        seq = self.next_seq()
        packet = self.link.transact(proto.build_hello_req(seq), timeout=self.response_timeout, expected_seq=seq)
        return proto.parse_hello_response(packet)

    def status(self) -> StatusResponse:
        seq = self.next_seq()
        packet = self.link.transact(proto.build_status_req(seq), timeout=self.response_timeout, expected_seq=seq)
        return proto.parse_status_response(packet)

    def all_black(self) -> StatusResponse:
        seq = self.next_seq()
        packet = self.link.transact(proto.build_all_black(seq), timeout=self.response_timeout, expected_seq=seq)
        return proto.parse_status_response(packet)

    def send_frame(self, frame_rgb: bytes, ww: int = 0, cw: int = 0, chunk_delay_s: float = DEFAULT_CHUNK_DELAY_S) -> CommitResponse:
        """Send one full 8x96 RGB frame and return the commit response."""
        frame_id = self.next_frame_id()
        timing = FrameTiming(frame_id=frame_id)
        self.last_frame_timing = timing
        frame_start = time.perf_counter()

        seq = self.next_seq()
        stage_start = time.perf_counter()
        self.link.write(proto.build_frame_begin(seq, frame_id, ww=ww, cw=cw), flush=False)
        timing.begin_ms = self._elapsed_ms(stage_start)
        timing.pacing_ms += self._pace_chunks(chunk_delay_s)

        # Pace each CDC write so the firmware parser can drain the 256-byte RX ring.
        for chunk_index, chunk_data in proto.iter_frame_chunks(frame_rgb):
            seq = self.next_seq()
            stage_start = time.perf_counter()
            self.link.write(proto.build_frame_chunk(seq, frame_id, chunk_index, chunk_data), flush=False)
            timing.chunks_ms += self._elapsed_ms(stage_start)
            timing.chunk_count += 1
            timing.pacing_ms += self._pace_chunks(chunk_delay_s)

        seq = self.next_seq()
        stage_start = time.perf_counter()
        self.link.write(proto.build_frame_commit(seq, frame_id), flush=True)
        timing.commit_write_ms = self._elapsed_ms(stage_start)

        stage_start = time.perf_counter()
        try:
            packet = self.link.read_packet(timeout=self.response_timeout, expected_seq=seq)
        finally:
            timing.response_wait_ms = self._elapsed_ms(stage_start)
            timing.total_ms = self._elapsed_ms(frame_start)

        return proto.parse_commit_response(packet)

    def send_solid(self, r: int, g: int, b: int, ww: int = 0, cw: int = 0, chunk_delay_s: float = DEFAULT_CHUNK_DELAY_S) -> CommitResponse:
        return self.send_frame(proto.solid_frame_rgb(r, g, b), ww=ww, cw=cw, chunk_delay_s=chunk_delay_s)

    @staticmethod
    def _pace_chunks(chunk_delay_s: float) -> float:
        if chunk_delay_s <= 0.0:
            return 0.0

        stage_start = time.perf_counter()
        if chunk_delay_s > PRECISE_SLEEP_THRESHOLD_S:
            time.sleep(chunk_delay_s)
            return PixelDevice._elapsed_ms(stage_start)

        deadline = time.perf_counter() + chunk_delay_s
        while time.perf_counter() < deadline:
            pass
        return PixelDevice._elapsed_ms(stage_start)

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return (time.perf_counter() - start) * 1000.0
