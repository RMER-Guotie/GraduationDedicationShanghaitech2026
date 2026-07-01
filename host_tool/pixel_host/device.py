"""High-level device operations built on the wire protocol."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import time

from . import protocol as proto
from .protocol import CommitResponse, HelloResponse, StatusResponse
from .serial_link import SerialLink


@dataclass
class PixelDevice:
    """Convenience API for one downstream controller board."""

    link: SerialLink
    response_timeout: float = 1.0

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

    def send_frame(self, frame_rgb: bytes, ww: int = 0, cw: int = 0) -> CommitResponse:
        """Send one full 8x96 RGB frame and return the commit response."""
        frame_id = self.next_frame_id()

        seq = self.next_seq()
        self.link.write(proto.build_frame_begin(seq, frame_id, ww=ww, cw=cw))

        for chunk_index, chunk_data in proto.iter_frame_chunks(frame_rgb):
            seq = self.next_seq()
            self.link.write(proto.build_frame_chunk(seq, frame_id, chunk_index, chunk_data))

        seq = self.next_seq()
        packet = self.link.transact(proto.build_frame_commit(seq, frame_id), timeout=self.response_timeout, expected_seq=seq)
        return proto.parse_commit_response(packet)

    def send_solid(self, r: int, g: int, b: int, ww: int = 0, cw: int = 0) -> CommitResponse:
        return self.send_frame(proto.solid_frame_rgb(r, g, b), ww=ww, cw=cw)
