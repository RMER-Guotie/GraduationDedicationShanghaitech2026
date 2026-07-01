"""Send ALL_BLACK to a Pixel Controller."""

from __future__ import annotations

import argparse

from .common import add_port_argument, close_device, open_device, print_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Force all outputs black")
    add_port_argument(parser)
    args = parser.parse_args()

    device = open_device(args)
    try:
        print_status(device.all_black())
    finally:
        close_device(device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
