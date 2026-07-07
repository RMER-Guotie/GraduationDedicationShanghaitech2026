"""Helpers for scanning and assigning multiple controller boards."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from . import protocol as proto
from .device import PixelDevice
from .serial_link import SerialLink, list_serial_ports


@dataclass(frozen=True)
class DeviceConfigEntry:
    """Host-side mapping from physical board ID to playback slot."""

    role_id: int
    slot_id: int | None = None
    uid_hash: int | None = None
    name: str = ""
    enabled: bool = True


@dataclass
class ConnectedDevice:
    """Opened device and identity discovered from HELLO."""

    port: str
    role_id: int
    slot_id: int | None
    uid_hash: int
    device: PixelDevice


def parse_uid(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value & 0xFFFFFFFF
    if isinstance(value, str):
        return int(value, 0) & 0xFFFFFFFF
    raise ValueError(f"bad uid_hash value: {value!r}")


def load_device_config(path: str | None) -> list[DeviceConfigEntry]:
    if not path:
        return []
    config_path = Path(path)
    if not config_path.exists():
        return []

    with config_path.open("r", encoding="utf-8") as file_obj:
        raw = json.load(file_obj)

    entries: list[DeviceConfigEntry] = []
    devices = raw.get("devices", [])
    if isinstance(devices, dict):
        for uid_text, item in devices.items():
            entries.append(
                DeviceConfigEntry(
                    role_id=int(item.get("role_id", item.get("role", 0))),
                    slot_id=parse_optional_int(item.get("slot", item.get("slot_id"))),
                    uid_hash=parse_uid(item.get("uid_hash", uid_text)),
                    name=str(item.get("name", "")),
                    enabled=bool(item.get("enabled", True)),
                )
            )
    else:
        for item in devices:
            entries.append(
                DeviceConfigEntry(
                    role_id=int(item.get("role_id", item.get("role", 0))),
                    slot_id=parse_optional_int(item.get("slot", item.get("slot_id"))),
                    uid_hash=parse_uid(item.get("uid_hash")),
                    name=str(item.get("name", "")),
                    enabled=bool(item.get("enabled", True)),
                )
            )

    for entry in entries:
        if entry.enabled and not 1 <= entry.role_id <= 20:
            raise ValueError(f"role_id must be 1..20, got {entry.role_id}")
        if entry.enabled and entry.slot_id is not None and not 1 <= entry.slot_id <= 8:
            raise ValueError(f"slot must be 1..8, got {entry.slot_id}")
    return entries


def parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def resolve_assignment(hello: proto.HelloResponse, entries: Iterable[DeviceConfigEntry]) -> tuple[int, int | None]:
    """Return physical role_id and optional playback slot for one HELLO."""
    for entry in entries:
        if not entry.enabled:
            continue
        if entry.role_id == hello.role_id:
            return entry.role_id, entry.slot_id
        if entry.uid_hash is not None and entry.uid_hash == hello.uid_hash:
            return entry.role_id, entry.slot_id
    return hello.role_id, None


def scan_and_open(
    ports: list[str] | None,
    baud: int,
    timeout: float,
    config_path: str | None = None,
) -> list[ConnectedDevice]:
    """Open ports that answer HELLO and keep successful links alive."""
    config_entries = load_device_config(config_path)
    port_list = ports if ports else list_serial_ports()
    connected: list[ConnectedDevice] = []

    for port in port_list:
        link = SerialLink(port, baudrate=baud, timeout=0.05)
        try:
            link.open()
            device = PixelDevice(link=link, response_timeout=timeout)
            hello = device.hello()
            role_id, slot_id = resolve_assignment(hello, config_entries)
            if not 1 <= role_id <= 20:
                raise ValueError(f"invalid role_id {role_id}")
            connected.append(ConnectedDevice(port=port, role_id=role_id, slot_id=slot_id, uid_hash=hello.uid_hash, device=device))
        except Exception:
            link.close()
            raise

    return connected
