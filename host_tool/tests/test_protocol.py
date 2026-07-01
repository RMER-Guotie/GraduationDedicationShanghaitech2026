"""Protocol self-tests that do not require hardware."""

from pixel_host import protocol as proto
from pixel_host.crc import crc16_ccitt_false


def test_crc_known_vector() -> None:
    assert crc16_ccitt_false(b"123456789") == 0x29B1


def test_packet_roundtrip() -> None:
    parser = proto.PacketParser()
    encoded = proto.encode_packet(proto.STATUS_REQ, seq=7)
    packets = parser.feed(encoded)
    assert len(packets) == 1
    assert packets[0].msg_type == proto.STATUS_REQ
    assert packets[0].seq == 7
    assert packets[0].payload == b""


def test_frame_chunking() -> None:
    frame = proto.solid_frame_rgb(1, 2, 3)
    chunks = list(proto.iter_frame_chunks(frame))
    assert len(chunks) == proto.FRAME_CHUNKS
    assert chunks[0][0] == 0
    assert chunks[0][1] == bytes((1, 2, 3)) * proto.LEDS_PER_CHUNK
    assert chunks[-1][0] == 15
    assert len(chunks[-1][1]) == proto.CHUNK_RGB_BYTES
