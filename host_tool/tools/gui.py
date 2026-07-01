"""Launch the PySide6 debug GUI."""

from __future__ import annotations

import sys

from pixel_host.gui import run


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

