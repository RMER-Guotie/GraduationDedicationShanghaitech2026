"""Packet and payload helpers for the Pixel Controller firmware protocol."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable, Iterator, Optional

from .crc import crc16_ccitt_false

SYNC = b"\x5a\xa5"
VERSION = 1
HEADER_SIZE = 7
CRC_SIZE = 2
MAX_PAYLOAD = 160

LANES = 8
LEDS_PER_LANE = 96
LEDS_PER_CHUNK = 48
CHUNK_RGB_BYTES = LEDS_PER_CHUNK * 3
FRAME_CHUNKS = 16

HELLO_REQ = 0x01
HELLO_RSP = 0x81
FRAME_BEGIN = 0x10
FRAME_RGB_CHUNK = 0x11
FRAME_COMMIT = 0x12
ALL_BLACK = 0x13
STATUS_REQ = 0x20
STATUS_RSP = 0xA0
ERROR_RSP = 0xE0

OK = 0
ERR_BAD_VERSION = 1
ERR_BAD_LENGTH = 2
ERR_BAD_CRC = 3
ERR_BAD_TYPE = 4
ERR_BAD_STATE = 5
ERR_BAD_FRAME_ID = 6
ERR_BAD_CHUNK = 7
ERR_INCOMPLETE_FRAME = 8
ERR_FAULT_ACTIVE = 9
ERR_RX_OVERFLOW = 10

STATUS_FLAG_FAULT = 0x0001
STATUS_FLAG_PENDING = 0x0002
STATUS_FLAG_HOST = 0x0004
STATUS_FLAG_TXN = 0x0008
STATUS_RSP_FORMAT = "<HBBHHHIIIHHII"
STATUS_RSP_SIZE = struct.calcsize(STATUS_RSP_FORMAT)


class ProtocolError(Exception):
    """Raised when a received packet cannot be parsed or validated."""


@dataclass(frozen=True)
class Packet:
    """One decoded firmware protocol packet."""

    msg_type: int
    seq: int
    flags: int
    payload: bytes


@dataclass(frozen=True)
class HelloResponse:
    uid_hash: int
    role_id: int
    lanes: int
    leds_per_lane: int
    chunk_rgb_bytes: int
    chunk_count: int
    protocol_version: int
    max_payload: int
    long_timeout_ms: int
    white_max_level: int


@dataclass(frozen=True)
class StatusResponse:
    status_flags: int
    active_link: int
    rc_stable_bits: int
    rx_used: int
    frame_id: int
    received_mask: int
    packet_count: int
    error_count: int
    current_ma: int
    ww_current: int
    cw_current: int
    uid_hash: int
    commit_count: int


@dataclass(frozen=True)
class CommitResponse:
    frame_id: int
    status: int
    received_mask: int


@dataclass(frozen=True)
class ErrorResponse:
    error_code: int
    detail: int


class PacketParser:
    """Incremental byte-stream parser matching the firmware state machine."""

    WAIT_SYNC0 = 0
    WAIT_SYNC1 = 1
    READ_HEADER = 2
    READ_PAYLOAD = 3
    READ_CRC0 = 4
    READ_CRC1 = 5

    def __init__(self) -> None:
        self.state = self.WAIT_SYNC0
        self.header = bytearray()
        self.payload = bytearray()
        self.payload_len = 0
        self.rx_crc = 0

    def reset(self) -> None:
        self.state = self.WAIT_SYNC0
        self.header.clear()
        self.payload.clear()
        self.payload_len = 0
        self.rx_crc = 0

    def feed(self, data: bytes) -> list[Packet]:
        """Feed bytes and return all complete packets decoded from them."""
        packets: list[Packet] = []
        for value in data:
            packet = self.feed_byte(value)
            if packet is not None:
                packets.append(packet)
        return packets

    def feed_byte(self, value: int) -> Optional[Packet]:
        """Feed one byte and return a packet only when one completes."""
        value &= 0xFF

        if self.state == self.WAIT_SYNC0:
            if value == SYNC[0]:
                self.state = self.WAIT_SYNC1
            return None

        if self.state == self.WAIT_SYNC1:
            if value == SYNC[1]:
                self.header.clear()
                self.state = self.READ_HEADER
            elif value != SYNC[0]:
                self.state = self.WAIT_SYNC0
            return None

        if self.state == self.READ_HEADER:
            self.header.append(value)
            if len(self.header) >= HEADER_SIZE:
                version, _msg_type, _seq, self.payload_len, _flags = unpack_header(bytes(self.header))
                if version != VERSION:
                    self.reset()
                    raise ProtocolError(f"bad protocol version {version}")
                if self.payload_len > MAX_PAYLOAD:
                    self.reset()
                    raise ProtocolError(f"payload too large {self.payload_len}")
                self.payload.clear()
                self.state = self.READ_CRC0 if self.payload_len == 0 else self.READ_PAYLOAD
            return None

        if self.state == self.READ_PAYLOAD:
            self.payload.append(value)
            if len(self.payload) >= self.payload_len:
                self.state = self.READ_CRC0
            return None

        if self.state == self.READ_CRC0:
            self.rx_crc = value
            self.state = self.READ_CRC1
            return None

        if self.state == self.READ_CRC1:
            self.rx_crc |= value << 8
            packet = decode_packet_parts(bytes(self.header), bytes(self.payload), self.rx_crc)
            self.reset()
            return packet

        self.reset()
        return None


def unpack_header(header: bytes) -> tuple[int, int, int, int, int]:
    """Return version, type, seq, payload_len, flags from a 7-byte header."""
    if len(header) != HEADER_SIZE:
        raise ProtocolError(f"bad header length {len(header)}")
    version = header[0]
    msg_type = header[1]
    seq, payload_len = struct.unpack_from("<HH", header, 2)
    flags = header[6]
    return version, msg_type, seq, payload_len, flags


def encode_packet(msg_type: int, seq: int, payload: bytes = b"", flags: int = 0) -> bytes:
    """Build one framed packet ready for serial transmission."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large: {len(payload)}")
    header = struct.pack("<BBHHB", VERSION, msg_type & 0xFF, seq & 0xFFFF, len(payload), flags & 0xFF)
    crc = crc16_ccitt_false(header + payload)
    return SYNC + header + payload + struct.pack("<H", crc)


def decode_packet_parts(header: bytes, payload: bytes, rx_crc: int) -> Packet:
    """Validate a packet after sync/header/payload/crc have been collected."""
    version, msg_type, seq, payload_len, flags = unpack_header(header)
    if version != VERSION:
        raise ProtocolError(f"bad protocol version {version}")
    if payload_len != len(payload):
        raise ProtocolError(f"payload length mismatch {payload_len} != {len(payload)}")
    calc_crc = crc16_ccitt_false(header + payload)
    if calc_crc != rx_crc:
        raise ProtocolError(f"bad crc calc=0x{calc_crc:04x} rx=0x{rx_crc:04x}")
    return Packet(msg_type=msg_type, seq=seq, flags=flags, payload=payload)


def build_hello_req(seq: int) -> bytes:
    return encode_packet(HELLO_REQ, seq)


def build_status_req(seq: int) -> bytes:
    return encode_packet(STATUS_REQ, seq)


def build_all_black(seq: int) -> bytes:
    return encode_packet(ALL_BLACK, seq)


def build_frame_begin(seq: int, frame_id: int, ww: int, cw: int, frame_crc32: int = 0) -> bytes:
    payload = struct.pack("<HBBHHI", frame_id & 0xFFFF, FRAME_CHUNKS, 0, ww & 0xFFFF, cw & 0xFFFF, frame_crc32)
    return encode_packet(FRAME_BEGIN, seq, payload)


def build_frame_chunk(seq: int, frame_id: int, chunk_index: int, rgb_data: bytes) -> bytes:
    if len(rgb_data) != CHUNK_RGB_BYTES:
        raise ValueError(f"chunk must be {CHUNK_RGB_BYTES} bytes")
    if not 0 <= chunk_index < FRAME_CHUNKS:
        raise ValueError(f"chunk_index out of range: {chunk_index}")
    payload = struct.pack("<HBB", frame_id & 0xFFFF, chunk_index, CHUNK_RGB_BYTES) + rgb_data
    return encode_packet(FRAME_RGB_CHUNK, seq, payload)


def build_frame_commit(seq: int, frame_id: int) -> bytes:
    return encode_packet(FRAME_COMMIT, seq, struct.pack("<H", frame_id & 0xFFFF))


def solid_frame_rgb(r: int, g: int, b: int) -> bytes:
    """Return one controller frame in lane-major RGB byte order."""
    pixel = bytes((r & 0xFF, g & 0xFF, b & 0xFF))
    return pixel * (LANES * LEDS_PER_LANE)


def iter_frame_chunks(frame_rgb: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield firmware chunk_index and 144-byte RGB data for an 8x96 frame."""
    expected = LANES * LEDS_PER_LANE * 3
    if len(frame_rgb) != expected:
        raise ValueError(f"frame must be {expected} bytes")

    for chunk_index in range(FRAME_CHUNKS):
        lane = chunk_index // 2
        half = chunk_index & 1
        pixel_start = lane * LEDS_PER_LANE + half * LEDS_PER_CHUNK
        byte_start = pixel_start * 3
        yield chunk_index, frame_rgb[byte_start : byte_start + CHUNK_RGB_BYTES]


def parse_hello_response(packet: Packet) -> HelloResponse:
    if packet.msg_type != HELLO_RSP:
        raise ProtocolError(f"expected HELLO_RSP, got 0x{packet.msg_type:02x}")
    if len(packet.payload) != 18:
        raise ProtocolError(f"bad HELLO_RSP length {len(packet.payload)}")
    values = struct.unpack("<IBBHHBBHHH", packet.payload)
    return HelloResponse(*values)


def parse_status_response(packet: Packet) -> StatusResponse:
    if packet.msg_type != STATUS_RSP:
        raise ProtocolError(f"expected STATUS_RSP, got 0x{packet.msg_type:02x}")
    if len(packet.payload) != STATUS_RSP_SIZE:
        raise ProtocolError(f"bad STATUS_RSP length {len(packet.payload)}")
    values = struct.unpack(STATUS_RSP_FORMAT, packet.payload)
    return StatusResponse(*values)


def parse_commit_response(packet: Packet) -> CommitResponse:
    if packet.msg_type != FRAME_COMMIT:
        raise ProtocolError(f"expected FRAME_COMMIT response, got 0x{packet.msg_type:02x}")
    if len(packet.payload) != 5:
        raise ProtocolError(f"bad FRAME_COMMIT response length {len(packet.payload)}")
    frame_id, status, received_mask = struct.unpack("<HBH", packet.payload)
    return CommitResponse(frame_id, status, received_mask)


def parse_error_response(packet: Packet) -> ErrorResponse:
    if packet.msg_type != ERROR_RSP:
        raise ProtocolError(f"expected ERROR_RSP, got 0x{packet.msg_type:02x}")
    if len(packet.payload) != 3:
        raise ProtocolError(f"bad ERROR_RSP length {len(packet.payload)}")
    error_code, detail = struct.unpack("<BH", packet.payload)
    return ErrorResponse(error_code, detail)


def format_uid(uid_hash: int) -> str:
    return f"0x{uid_hash:08x}"


def status_flags_to_text(flags: int) -> str:
    names = []
    if flags & STATUS_FLAG_FAULT:
        names.append("fault")
    if flags & STATUS_FLAG_PENDING:
        names.append("pending_show")
    if flags & STATUS_FLAG_HOST:
        names.append("host_control")
    if flags & STATUS_FLAG_TXN:
        names.append("transaction")
    return ",".join(names) if names else "ok"
