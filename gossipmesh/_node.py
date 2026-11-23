import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ._ax25 import KissReader, kiss_wrap, parse_ui, ui_frame
from ._framelog import FrameSink
from ._station import Station


class Link(Protocol):
    def send(self, data: bytes) -> None: ...

    def recv(self) -> bytes: ...


class TcpLink:
    """KISS over TCP, as Direwolf (port 8001) and UZ7HO soundmodem offer."""

    def __init__(self, host: str, port: int) -> None:
        try:
            self._sock = socket.create_connection((host, port), timeout=10)
        except OSError as e:
            raise ConnectionError(f"could not reach the KISS TNC at {host}:{port}: {e}") from e
        self._sock.settimeout(0.2)

    def send(self, data: bytes) -> None:
        self._sock.sendall(data)

    def recv(self) -> bytes:
        try:
            data = self._sock.recv(4096)
        except TimeoutError:
            return b""
        if not data:
            raise ConnectionError("the TNC closed the KISS connection")
        return data


class SerialLink:
    """KISS over a serial port to a hardware TNC already in KISS mode."""

    def __init__(self, port: str, baud: int) -> None:
        try:
            import serial
        except ImportError as e:
            raise RuntimeError(
                "serial TNCs need the serial extra: pip install gossipmesh[serial]"
            ) from e
        self._port: Any = serial.Serial(port, baud, timeout=0.2)

    def send(self, data: bytes) -> None:
        self._port.write(data)

    def recv(self) -> bytes:
        data: bytes = self._port.read(4096)
        return data


def _stderr(text: str) -> None:
    print(f"gossipmesh: {text}", file=sys.stderr, flush=True)


class Blocklist:
    """Message ids not to relay, one hex id per line, re-read whenever the file changes."""

    def __init__(self, path: Path, say: Callable[[str], None] = _stderr) -> None:
        self.path = path
        self.say = say
        self._seen: tuple[int, int] | None = None

    def add(self, msg_id: bytes) -> None:
        self._rewrite([*self._lines(), msg_id.hex()])

    def remove(self, msg_id: bytes) -> None:
        """Drop every line naming msg_id, keeping the rest of the file as it was."""
        lines = self._lines()
        self._rewrite([ln for ln in lines if ln.split("#")[0].strip().lower() != msg_id.hex()])

    def _lines(self) -> list[str]:
        try:
            return _read_text(self.path).splitlines()
        except FileNotFoundError:
            return []

    def _rewrite(self, lines: list[str]) -> None:
        # UTF-8 whatever the file was before, and via a temporary file, so the node loop never
        # reads a half-written list
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        tmp.replace(self.path)

    def poll(self) -> set[bytes] | None:
        """Every id in the file if it changed since the last call, otherwise None."""
        try:
            st = self.path.stat()
        except FileNotFoundError:
            st = None
        # size as well as mtime: two quick edits can share a timestamp
        seen = (st.st_mtime_ns, st.st_size) if st else (0, -1)
        if seen == self._seen:
            return None
        self._seen = seen
        if st is None:
            return set()
        ids = set()
        try:
            text = _read_text(self.path)
        except OSError as e:
            self.say(f"{self.path}: {e}; keeping the previous blocklist")
            return None
        for n, line in enumerate(text.splitlines(), 1):
            line = line.split("#")[0].strip()
            try:
                if line:
                    ids.add(_msg_id(line))
            except ValueError:
                self.say(f"{self.path}:{n}: not a message id, ignored")
        return ids


def _read_text(path: Path) -> str:
    # PowerShell 5's `>` writes UTF-16 with a BOM, and Notepad may add a UTF-8 BOM
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _msg_id(text: str) -> bytes:
    raw = bytes.fromhex(text)
    if len(raw) != 8:
        raise ValueError(f"{text!r} is not a 16-digit message id")
    return raw


class Outbox:
    """A folder to drop message files into. Each one is sent once, then moved to sent/.

    A file that cannot be sent (too big, unreadable) moves to failed/ instead, so one bad file
    never stops the node or blocks the ones after it.
    """

    # editor swap files, Explorer and Finder droppings
    IGNORE = ("Thumbs.db", "desktop.ini")

    def __init__(
        self, path: Path, send: Callable[[bytes, float], None], say: Callable[[str], None] = _stderr
    ) -> None:
        self.path = path
        self.send = send
        self.say = say

    def poll(self, now: float) -> None:
        for f in sorted(self.path.iterdir()):
            if not f.is_file() or f.name.startswith(".") or f.name.endswith(("~", ".swp")):
                continue
            if f.name in self.IGNORE:
                continue
            try:
                # a file touched in the last second may still be being written
                if now - f.stat().st_mtime < 1.0:
                    continue
                self.send(f.read_bytes(), now)
                folder = "sent"
            except (OSError, ValueError) as e:
                self.say(f"{f}: not sent: {e}")
                folder = "failed"
            try:
                (self.path / folder).mkdir(exist_ok=True)
                f.replace(self.path / folder / f"{int(now)}-{f.name}")
            except OSError as e:
                self.say(f"{f}: could not move it to {folder}/: {e}")


def _apply_blocklist(
    station: Station,
    before: set[bytes],
    now_blocked: set[bytes],
    now: float,
    log: FrameSink | None,
    say: Callable[[str], None],
) -> None:
    for msg_id in sorted(now_blocked - before):
        station.block(msg_id)
        say(f"blocking {msg_id.hex()}")
        if log:
            log.note(now, "block", msg_id)
    for msg_id in sorted(before - now_blocked):
        station.unblock(msg_id)
        say(f"unblocking {msg_id.hex()}")
        if log:
            log.note(now, "unblock", msg_id)


def run(
    station: Station,
    link: Link,
    airtime: Callable[[int], float],
    clock: Callable[[], float] = time.time,
    log: FrameSink | None = None,
    blocklist: Blocklist | None = None,
    outbox: Outbox | None = None,
    tick: Callable[[float], None] | None = None,
    stop: threading.Event | None = None,
    say: Callable[[str], None] = lambda text: print(text, flush=True),
) -> None:
    """Pass frames between the station and the TNC until the link fails or stop is set.

    The TNC does carrier sense; this loop only holds back the next frame until the last one has
    had time to go out, so the station decides what to send with fresh information. tick runs
    on every pass, in this thread, which is where anything else may touch the station.
    """
    reader = KissReader()
    hold_until = 0.0
    # a reconnect starts a new loop on the same station, which may already block some ids
    blocked = set(station.blocked)
    while stop is None or not stop.is_set():
        data = link.recv()
        now = clock()
        ids = blocklist.poll() if blocklist else None
        if ids is not None:
            _apply_blocklist(station, blocked, ids, now, log, say)
            blocked = ids
        if outbox:
            outbox.poll(now)
        if tick:
            tick(now)
        for frame in reader.feed(data):
            ui = parse_ui(frame)
            if ui is not None:
                if log:
                    log.write(now, "rx", ui[0], ui[1])
                station.receive(ui[1], ui[0], now)
        due = station.due()
        if due is None or due > now or now < hold_until:
            continue
        info = station.transmit(now)
        if info is not None:
            if log:
                log.write(now, "tx", station.call, info)
            link.send(kiss_wrap(ui_frame(station.call, info)))
            hold_until = now + airtime(len(info))
