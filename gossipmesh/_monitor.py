import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from ._framelog import FrameSink
from ._message import check_call
from ._node import Blocklist
from ._station import Delivery, MessageState, Station

_KINDS = {1: "coded", 2: "coded", 3: "status"}
DUTY_WINDOW = 600.0
MAX_NEIGHBOURS = 200


@dataclass(frozen=True)
class Received:
    msg_id: bytes
    originator: str
    at: float
    size: int
    text: str | None
    signature: str


@dataclass(frozen=True)
class Neighbour:
    call: str
    last: float
    frames: int


@dataclass(frozen=True)
class Sent:
    msg_id: bytes
    at: float
    source: str


@dataclass(frozen=True)
class Snapshot:
    now: float
    state: str
    detail: str = ""
    messages: tuple[MessageState, ...] = ()
    blocked: frozenset[bytes] = frozenset()
    received: tuple[Received, ...] = ()
    neighbours: tuple[Neighbour, ...] = ()
    sent: tuple[Sent, ...] = ()
    events: tuple[str, ...] = ()
    event_count: int = 0
    tx_frames: int = 0
    tx_airtime: float = 0.0
    rx_frames: int = 0
    rx_airtime: float = 0.0
    duty: float = 0.0
    trusted_only: bool = False
    notice: str = ""
    notice_count: int = 0


def short_text(body: bytes, limit: int | None = 500) -> str | None:
    """The body as text, if it is readable UTF-8 no longer than limit characters."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if (limit is not None and len(text) > limit) or any(
        not c.isprintable() and c not in "\r\n\t" for c in text
    ):
        return None
    return text


def signature_note(d: Delivery) -> str:
    if d.envelope.signature is not None and d.verified is None:
        return "signed by an untrusted key"
    return {True: "signature ok", False: "signature bad", None: "unsigned"}[d.verified]


class Monitor:
    """What a running node is doing, for the TUI.

    The node loop owns the station. It reports frames through write() and note(), deliveries
    through delivered(), and calls tick() on every pass, which runs the commands the UI queued
    and publishes a fresh snapshot. The UI thread only reads snapshot() and queues commands, so
    nothing touches the station from two threads.
    """

    def __init__(
        self,
        station: Station,
        originate: Callable[[bytes, float], bytes],
        airtime: Callable[[int], float],
        log: FrameSink | None = None,
        blocklist: Blocklist | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.station = station
        self.originate = originate
        self.airtime = airtime
        self.log = log
        self.blocklist = blocklist
        self.clock = clock
        self._commands: queue.SimpleQueue[Callable[[float], None]] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._snapshot = Snapshot(clock(), "connecting", trusted_only=station.relay_trusted_only)
        self._received: list[Received] = []
        self._neighbours: dict[str, Neighbour] = {}
        self._sent: list[Sent] = []
        self._events: deque[str] = deque(maxlen=500)
        self._event_count = 0
        self._recent_tx: deque[tuple[float, float]] = deque()
        self._tx_frames, self._tx_air = 0, 0.0
        self._rx_frames, self._rx_air = 0, 0.0
        self._notice = ""
        self._notice_count = 0

    def set_state(self, state: str, detail: str = "") -> None:
        """Connection state: connecting, connected, stopped or error. Any thread."""
        with self._lock:
            self._snapshot = replace(self._snapshot, state=state, detail=detail)

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    # the UI thread queues these; they run in the node thread at the next tick

    def send_text(self, text: str) -> None:
        self._commands.put(lambda now: self._send(text.encode("utf-8"), now, "typed text"))

    def send_file(self, path: Path) -> None:
        self._commands.put(lambda now: self._send_file(path, now))

    def block(self, msg_id: bytes) -> None:
        self._commands.put(lambda now: self._set_block(msg_id, True, now))

    def unblock(self, msg_id: bytes) -> None:
        self._commands.put(lambda now: self._set_block(msg_id, False, now))

    def set_trusted_only(self, on: bool) -> None:
        self._commands.put(lambda now: self._trusted_only(on, now))

    # the node thread calls these

    def write(self, now: float, direction: str, src: str, info: bytes) -> None:
        if self.log:
            self.log.write(now, direction, src, info)
        air = self.airtime(len(info))
        kind = _KINDS.get(info[0] & 15, "other") if info else "other"
        try:
            src = check_call(src)
        except ValueError:
            # any 7-bit text can sit in an AX.25 address, escape codes included
            src = "-"
        if direction == "tx":
            self._tx_frames += 1
            self._tx_air += air
            self._recent_tx.append((now, air))
        else:
            self._rx_frames += 1
            self._rx_air += air
            if src != "-":
                old = self._neighbours.get(src)
                self._neighbours[src] = Neighbour(src, now, (old.frames if old else 0) + 1)
        self._event(now, f"{direction} {src} {kind}, {len(info)} bytes")

    def note(self, now: float, kind: str, msg_id: bytes) -> None:
        if self.log:
            self.log.note(now, kind, msg_id)
        self._event(now, f"{kind} {msg_id.hex()}")

    def say(self, text: str) -> None:
        self._event(self.clock(), text)

    def delivered(self, d: Delivery) -> None:
        env = d.envelope
        note = signature_note(d)
        self._received.append(
            Received(
                env.msg_id, env.originator, d.at, len(env.body), short_text(env.body, None), note
            )
        )
        self._event(d.at, f"decoded {env.msg_id.hex()} from {env.originator}, {note}")

    def send_now(self, body: bytes, now: float, source: str) -> None:
        """Originate body, raising ValueError if it cannot be sent. Node thread only."""
        msg_id = self.originate(body, now)
        self._sent.append(Sent(msg_id, now, source))
        self._notify(now, f"Sent {msg_id.hex()} from {source}, {len(body)} bytes")

    def tick(self, now: float) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break
            command(now)
        self._publish(now)

    def _publish(self, now: float) -> None:
        while self._recent_tx and self._recent_tx[0][0] < now - DUTY_WINDOW:
            self._recent_tx.popleft()
        duty = sum(air for _, air in self._recent_tx) / DUTY_WINDOW
        neighbours = sorted(self._neighbours.values(), key=lambda n: -n.last)[:MAX_NEIGHBOURS]
        with self._lock:
            self._snapshot = Snapshot(
                now,
                self._snapshot.state,
                self._snapshot.detail,
                tuple(self.station.messages()),
                self.station.blocked,
                tuple(self._received),
                tuple(neighbours),
                tuple(self._sent),
                tuple(self._events),
                self._event_count,
                self._tx_frames,
                self._tx_air,
                self._rx_frames,
                self._rx_air,
                duty,
                self.station.relay_trusted_only,
                self._notice,
                self._notice_count,
            )

    def _event(self, now: float, text: str) -> None:
        self._events.append(f"{time.strftime('%H:%M:%S', time.localtime(now))}  {text}")
        self._event_count += 1

    def _notify(self, now: float, text: str) -> None:
        self._notice = text
        self._notice_count += 1
        self._event(now, text)

    def _send(self, body: bytes, now: float, source: str) -> None:
        try:
            self.send_now(body, now, source)
        except ValueError as e:
            self._notify(now, f"Not sent: {e}")

    def _send_file(self, path: Path, now: float) -> None:
        try:
            body = path.read_bytes()
        except OSError as e:
            self._notify(now, f"Could not read {path}: {e.strerror or e}")
            return
        self._send(body, now, str(path))

    def _set_block(self, msg_id: bytes, on: bool, now: float) -> None:
        if self.blocklist:
            # the node loop picks the change up from the file, so the file stays the record
            try:
                (self.blocklist.add if on else self.blocklist.remove)(msg_id)
            except OSError as e:
                self._notify(now, f"Could not update {self.blocklist.path}: {e.strerror or e}")
                return
        elif on:
            self.station.block(msg_id)
            self.note(now, "block", msg_id)
        else:
            self.station.unblock(msg_id)
            self.note(now, "unblock", msg_id)
        self._notify(now, f"{'Blocked' if on else 'Unblocked'} {msg_id.hex()}")

    def _trusted_only(self, on: bool, now: float) -> None:
        if on and not self.station.keys:
            self._notify(now, "Relaying trusted messages only needs --trust")
            return
        self.station.relay_trusted_only = on
        self._notify(now, "Relaying trusted messages only" if on else "Relaying every message")
