"""Start the application.

    python -m tools.run

Binds to localhost by default. Pass --lan to also listen on the local network, which is
what makes the document inbox reachable from a phone to photograph a receipt.
"""

from __future__ import annotations

import argparse
import socket
import sys
import webbrowser
from pathlib import Path


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start de boekhouding")
    parser.add_argument("--poort", type=int, default=8777)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="ook bereikbaar op het lokale netwerk, bijvoorbeeld vanaf je telefoon",
    )
    parser.add_argument("--geen-browser", action="store_true")
    argumenten = parser.parse_args(argv)

    import uvicorn

    from app import db

    host = "0.0.0.0" if argumenten.lan else "127.0.0.1"
    adres = f"http://127.0.0.1:{argumenten.poort}"

    db.ensure_directories()
    print(f"Gegevens: {db.DATA_DIR}")
    if db.DATA_DIR == Path.home() / db.OUDE_DATA_DIR:
        print("  Deze map staat in Documents, waar OneDrive hem kan gaan synchroniseren.")
        print("  Verhuizen mag: sluit dit venster en verplaats de map naar")
        print(f"  {Path.home() / 'Boekhouding'}. Het programma vindt hem daar zelf.")
    print(f"Draait op {adres}")
    if argumenten.lan:
        print(f"Op je telefoon: http://{local_ip()}:{argumenten.poort}")

    if not argumenten.geen_browser:
        webbrowser.open(adres)

    uvicorn.run("app.web.main:app", host=host, port=argumenten.poort, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
