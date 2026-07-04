"""Shared CLI helpers."""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

from pixel_host.device import PixelDevice
from pixel_host.serial_link import SerialLink
from pixel_host import protocol as proto


def add_port_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("port", help="Serial port, for example COM5")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--timeout", type=float, default=1.0, help="Response timeout in seconds")


def open_device(args: argparse.Namespace) -> PixelDevice:
    link = SerialLink(args.port, baudrate=args.baud, timeout=0.05)
    link.open()
    return PixelDevice(link=link, response_timeout=args.timeout)


def close_device(device: PixelDevice) -> None:
    device.link.close()


def print_hello(hello: proto.HelloResponse) -> None:
    print(f"uid_hash={proto.format_uid(hello.uid_hash)} role_id=0x{hello.role_id:02x}")
    print(f"lanes={hello.lanes} leds_per_lane={hello.leds_per_lane} chunks={hello.chunk_count}")
    print(f"protocol={hello.protocol_version} max_payload={hello.max_payload} white_max={hello.white_max_level}")
    print(f"long_timeout_ms={hello.long_timeout_ms}")


def print_status(status: proto.StatusResponse) -> None:
    print(f"uid_hash={proto.format_uid(status.uid_hash)} flags={proto.status_flags_to_text(status.status_flags)}")
    print(f"active_link={status.active_link} rc_bits=0b{status.rc_stable_bits:04b} rx_used={status.rx_used}")
    print(f"current_ma={status.current_ma} ww={status.ww_current} cw={status.cw_current}")
    print(f"frame_id={status.frame_id} received_mask=0x{status.received_mask:04x}")
    print(f"packet_count={status.packet_count} error_count={status.error_count} commit_count={status.commit_count}")


def print_commit(commit: proto.CommitResponse) -> None:
    print(f"frame_id={commit.frame_id} status={commit.status} received_mask=0x{commit.received_mask:04x}")
