"""Generate 32x48 logical effect sequences as pixelbin files."""

from __future__ import annotations

import argparse

from pixel_host.effect_sequences import iter_effect_frames
from pixel_host.pixelbin import DEFAULT_BOARD_COUNT, write_pixelbin


EFFECTS = ("solid", "columns", "boards", "moving_bar", "breath", "rainbow", "checker", "power_stress")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a 32x48 effect sequence pixelbin")
    parser.add_argument("--output", required=True, help="Output .pixelbin path")
    parser.add_argument("--effect", choices=EFFECTS, default="columns")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--boards", type=int, default=DEFAULT_BOARD_COUNT)
    parser.add_argument("--rgb", nargs=3, type=int, default=(255, 0, 0), metavar=("R", "G", "B"))
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--direction", choices=("x", "y"), default="x")
    parser.add_argument("--ww", type=int, default=0)
    parser.add_argument("--cw", type=int, default=0)
    args = parser.parse_args()

    if args.seconds <= 0.0:
        raise SystemExit("--seconds must be positive")
    if args.fps < 1:
        raise SystemExit("--fps must be positive")
    if not 1 <= args.boards <= 8:
        raise SystemExit("--boards must be 1..8")

    frame_count = max(1, int(round(args.seconds * args.fps)))
    frames = iter_effect_frames(
        args.effect,
        frame_count=frame_count,
        fps=args.fps,
        board_count=args.boards,
        rgb=tuple(args.rgb),
        speed=args.speed,
        direction=args.direction,
        ww=args.ww,
        cw=args.cw,
    )
    count = write_pixelbin(args.output, frames, fps=args.fps, board_count=args.boards)
    print(
        f"wrote {count} frames to {args.output} "
        f"effect={args.effect} geometry={args.boards * 8}x48 fps={args.fps}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
