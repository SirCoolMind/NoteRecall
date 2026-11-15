"""Pick the port NoteRecall listens on: PORT (default 8756), or the next free one.

Run directly (`python port.py`) it prints the port, so start.bat / start.sh can
open the browser at the right address before the server starts. server.py calls
pick() too, for when it is started by hand.
"""

import os
import socket
import sys

DEFAULT_PORT = 8756
TRIES = 20          # 8756 .. 8775


def is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":
            # Match uvicorn, which sets SO_REUSEADDR on Linux/macOS: otherwise a
            # port still in TIME_WAIT after a restart would look taken. Never on
            # Windows, where SO_REUSEADDR lets a socket share a port in use.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick(host: str, start: int, tries: int = TRIES) -> int:
    """The first free port from start upwards; start itself if none is free
    (the server then reports the clash as before)."""
    for port in range(start, start + tries):
        if is_free(host, port):
            return port
    return start


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        start = int(os.environ.get("PORT") or DEFAULT_PORT)
    except ValueError:
        start = DEFAULT_PORT
    print(pick(host, start))
    sys.exit(0)
