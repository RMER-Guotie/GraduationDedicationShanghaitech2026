"""Send one solid-color frame to a Pixel Controller."""

from __future__ import annotations

import argparse

from .common import add_port_argument, close_device, open_device, print_commit


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one solid RGB frame")
    add_port_argument(parser)
    parser.add_argument("--rgb", nargs=3, type=int, metavar=("R", "G", "B"), required=True)
    parser.add_argument("--ww", type=int, default=0, help="Warm white level 0..1000")
    parser.add_argument("--cw", type=int, default=0, help="Cold white level 0..1000")
    args = parser.parse_args()

    r, g, b = args.rgb
    device = open_device(args)
    try:
        print_commit(device.send_solid(r, g, b, ww=args.ww, cw=args.cw))
    finally:
        close_device(device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
