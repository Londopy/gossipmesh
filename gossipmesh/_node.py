import socket
import time
from collections.abc import Callable
from typing import Any, Protocol

from ._ax25 import KissReader, kiss_wrap, parse_ui, ui_frame
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


def run(
    station: Station,
    link: Link,
    airtime: Callable[[int], float],
    clock: Callable[[], float] = time.time,
) -> None:
    """Pass frames between the station and the TNC until the link fails.

    The TNC does carrier sense; this loop only holds back the next frame until the last one has
    had time to go out, so the station decides what to send with fresh information.
    """
    reader = KissReader()
    hold_until = 0.0
    while True:
        data = link.recv()
        now = clock()
        for frame in reader.feed(data):
            ui = parse_ui(frame)
            if ui is not None:
                station.receive(ui[1], ui[0], now)
        due = station.due()
        if due is None or due > now or now < hold_until:
            continue
        info = station.transmit(now)
        if info is not None:
            link.send(kiss_wrap(ui_frame(station.call, info)))
            hold_until = now + airtime(len(info))
