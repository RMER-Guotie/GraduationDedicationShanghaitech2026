"""Launch the offline video-to-pixelbin generator GUI."""

from __future__ import annotations

from pixel_host.generator_gui import run


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
