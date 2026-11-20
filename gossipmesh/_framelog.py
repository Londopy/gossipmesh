from pathlib import Path

from ._station import Delivery, Station

# replays never transmit, so this only needs to be a valid call nobody on air will use
_REPLAY_CALL = "Q0LOG"


class FrameLog:
    """Appends every frame a node sends or hears, one per line: time, tx or rx, source, hex."""

    def __init__(self, path: Path) -> None:
        self._file = path.open("a", encoding="ascii", buffering=1)

    def write(self, now: float, direction: str, src: str, info: bytes) -> None:
        self._file.write(f"{now:.3f} {direction} {src} {info.hex()}\n")


def replay(path: Path, keys: dict[str, bytes] | None = None) -> list[Delivery]:
    """Every message the logged frames are enough to decode."""
    station = Station(_REPLAY_CALL, keys=keys)
    for n, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        try:
            t, _, src, info = line.split()
            station.receive(bytes.fromhex(info), src, float(t))
        except ValueError as e:
            raise ValueError(f"{path}:{n}: not a frame log line") from e
    return list(station.delivered.values())
