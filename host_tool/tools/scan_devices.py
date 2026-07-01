"""Scan serial ports and print HELLO responses."""

from __future__ import annotations

import argparse

from pixel_host.device import PixelDevice
from pixel_host.serial_link import SerialLink, list_serial_ports
from .common import print_hello


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan COM ports for Pixel Controller devices")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--timeout", type=float, default=0.5)
    parser.add_argument("--ports", nargs="*", help="Optional explicit port list")
    args = parser.parse_args()

    ports = args.ports if args.ports else list_serial_ports()
    if not ports:
        print("no serial ports found")
        return 1

    found = 0
    for port in ports:
        try:
            with SerialLink(port, baudrate=args.baud, timeout=0.05) as link:
                device = PixelDevice(link=link, response_timeout=args.timeout)
                hello = device.hello()
                print(f"[{port}]")
                print_hello(hello)
                found += 1
        except Exception as exc:
            print(f"[{port}] no response: {exc}")

    return 0 if found else 2


if __name__ == "__main__":
    raise SystemExit(main())
