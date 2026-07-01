"""Serial transport helper for USB CDC COM ports and UART debug links."""

from __future__ import annotations

from contextlib import AbstractContextManager
import time
from typing import Iterable, Optional

from .protocol import Packet, PacketParser, ProtocolError


class SerialUnavailable(RuntimeError):
    """Raised when pyserial is not installed."""


def _serial_module():
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise SerialUnavailable("pyserial is required: pip install -r host_tool/requirements.txt") from exc
    return serial


def list_serial_ports() -> list[str]:
    """Return currently visible serial port device names."""
    serial = _serial_module()
    from serial.tools import list_ports  # type: ignore

    return [port.device for port in list_ports.comports()]


class SerialLink(AbstractContextManager["SerialLink"]):
    """Small blocking serial link wrapper with an incremental packet parser."""

    def __init__(self, port: str, baudrate: int = 921600, timeout: float = 0.05) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None
        self._parser = PacketParser()

    def open(self) -> None:
        serial = _serial_module()
        self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout, write_timeout=self.timeout)
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def __enter__(self) -> "SerialLink":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def write(self, data: bytes) -> None:
        if self._serial is None:
            raise RuntimeError("serial link is not open")
        self._serial.write(data)
        self._serial.flush()

    def read_packet(self, timeout: float = 1.0, expected_seq: Optional[int] = None) -> Packet:
        """Read until a valid packet arrives or timeout expires."""
        if self._serial is None:
            raise RuntimeError("serial link is not open")

        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            chunk = self._serial.read(64)
            if not chunk:
                continue
            try:
                for packet in self._parser.feed(chunk):
                    if expected_seq is None or packet.seq == expected_seq:
                        return packet
            except ProtocolError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise TimeoutError(f"no valid packet before timeout; last parser error: {last_error}") from last_error
        raise TimeoutError("no packet before timeout")

    def transact(self, request: bytes, timeout: float = 1.0, expected_seq: Optional[int] = None) -> Packet:
        """Write one request and wait for one response packet."""
        self.write(request)
        return self.read_packet(timeout=timeout, expected_seq=expected_seq)
