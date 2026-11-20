import sys
from dataclasses import dataclass
from pathlib import Path

from ._message import check_call
from ._station import Delivery, Params, Station

# replays never transmit, so this only needs to be a valid call nobody on air will use
_REPLAY_CALL = "Q0LOG"


class FrameLog:
    """Appends every frame a node sends or hears, one per line: time, tx or rx, source, hex.

    Blocklist changes go in as `block` and `unblock` lines carrying the message id.
    """

    def __init__(self, path: Path) -> None:
        self._file = path.open("a", encoding="ascii", buffering=1)

    def write(self, now: float, direction: str, src: str, info: bytes) -> None:
        try:
            src = check_call(src)
        except ValueError:
            # a hostile frame can carry any source; keep the line one token per field
            src = "-"
        self._file.write(f"{now:.3f} {direction} {src} {info.hex()}\n")

    def note(self, now: float, kind: str, msg_id: bytes) -> None:
        self._file.write(f"{now:.3f} {kind} - {msg_id.hex()}\n")


@dataclass
class Replay:
    delivered: list[Delivery]
    blocked: set[bytes]
    skipped: int


def replay(path: Path, keys: dict[str, bytes] | None = None) -> Replay:
    """Every message the logged frames are enough to decode."""
    station = Station(_REPLAY_CALL, Params(max_msgs=1_000_000), keys=keys, listen_only=True)
    blocked: set[bytes] = set()
    skipped = 0
    text = path.read_bytes().decode("ascii", errors="replace")
    for n, line in enumerate(text.splitlines(), 1):
        try:
            t, kind, src, data = line.split()
            now, raw = float(t), bytes.fromhex(data)
        except ValueError:
            print(f"gossipmesh: {path}:{n}: not a frame log line, skipped", file=sys.stderr)
            skipped += 1
            continue
        if kind in ("rx", "tx"):
            station.receive(raw, src, now)
        elif kind == "block":
            blocked.add(raw)
        elif kind == "unblock":
            blocked.discard(raw)
    return Replay(list(station.delivered.values()), blocked, skipped)
