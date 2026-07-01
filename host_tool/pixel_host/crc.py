"""CRC helpers for the Pixel Controller host protocol."""

CRC16_CCITT_FALSE_INIT = 0xFFFF
CRC16_CCITT_FALSE_POLY = 0x1021


def crc16_ccitt_false(data: bytes, initial: int = CRC16_CCITT_FALSE_INIT) -> int:
    """Return CRC16-CCITT-FALSE over *data*."""
    crc = initial & 0xFFFF
    for value in data:
        crc ^= (value & 0xFF) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC16_CCITT_FALSE_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc
