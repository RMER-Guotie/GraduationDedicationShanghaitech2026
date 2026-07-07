"""Generate local pixelbin files for multi-board playback tests."""

from __future__ import annotations

import argparse
import math

from pixel_host import patterns
from pixel_host import protocol as proto
from pixel_host.pixelbin import DEFAULT_BOARD_COUNT, write_pixelbin


def clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def breath_frame(frame_index: int, frame_count: int, board_index: int) -> bytes:
    phase = (frame_index / max(1, frame_count)) * math.tau
    level = 0.5 - 0.5 * math.cos(phase)
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 255),
    ]
    r, g, b = colors[board_index % len(colors)]
    return proto.solid_frame_rgb(clamp_byte(r * level), clamp_byte(g * level), clamp_byte(b * level))


def iter_frames(args: argparse.Namespace):
    for frame_index in range(args.frames):
        if args.pattern == "solid":
            base = proto.solid_frame_rgb(args.rgb[0], args.rgb[1], args.rgb[2])
            board_frames = [base for _board in range(args.boards)]
        elif args.pattern == "lane_test":
            base = patterns.lane_test()
            board_frames = [base for _board in range(args.boards)]
        elif args.pattern == "breath":
            board_frames = [breath_frame(frame_index, args.frames, board) for board in range(args.boards)]
        else:
            raise ValueError(f"unknown pattern {args.pattern}")

        yield args.ww, args.cw, board_frames


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local pixelbin test file")
    parser.add_argument("--output", required=True, help="Output .pixelbin path")
    parser.add_argument("--pattern", choices=("solid", "lane_test", "breath"), default="lane_test")
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--boards", type=int, default=DEFAULT_BOARD_COUNT)
    parser.add_argument("--rgb", nargs=3, type=int, default=(255, 0, 0))
    parser.add_argument("--ww", type=int, default=0)
    parser.add_argument("--cw", type=int, default=0)
    args = parser.parse_args()

    if not 1 <= args.boards <= 8:
        raise SystemExit("--boards must be 1..8")
    if args.frames < 1:
        raise SystemExit("--frames must be positive")

    count = write_pixelbin(args.output, iter_frames(args), fps=args.fps, board_count=args.boards)
    print(f"wrote {count} frames to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
