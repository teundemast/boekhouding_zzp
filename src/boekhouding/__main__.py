"""Zodat `python -m boekhouding` ook werkt, niet alleen het `boekhouding`-commando."""

from __future__ import annotations

import sys

from boekhouding.cli import main

if __name__ == "__main__":
    sys.exit(main())
