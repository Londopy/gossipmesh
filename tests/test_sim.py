import random
from pathlib import Path

import pytest

from gossipmesh import Params, Station
from gossipmesh._ax25 import KissReader, kiss_wrap, parse_ui, ui_frame
from gossipmesh._framelog import FrameLog, replay
from gossipmesh._node import Blocklist, run
from gossipmesh._baselines import UncodedNode
from gossipmesh._sim import Scenario, channel, compare, place
from gossipmesh._sim import run as simulate


@pytest.mark.parametrize("strategy", ["coded", "uncoded"])
def test_reaches_every_station_on_a_small_map(strategy: str) -> None:
    sc = Scenario(stations=8, area=2.0, size=2000)
    rng = random.Random(4)
    r = simulate(strategy, sc, place(sc, rng), rng)
    assert r.delivered == 7
    assert r.last_tx < sc.limit, "stations kept transmitting until the time limit"


def test_receivers_that_hear_the_same_frames_do_not_ask_in_lockstep() -> None:
    # the first bench run: three stations on one channel, a quarter of frames lost, and both
    # receivers' statuses colliding on every round
    sc = Scenario(stations=3, area=0.3, loss=0.24, size=10_000, limit=3600)
    (coded,) = compare(sc, runs=5, seed=3, strategies=("coded",))
    assert sum(r.delivered for r in coded) == 10


@pytest.mark.slow
def test_coding_saves_airtime_over_the_same_protocol_uncoded() -> None:
    coded, uncoded = compare(Scenario(), runs=3, seed=1, strategies=("coded", "uncoded"))
    for rs in (coded, uncoded):
        assert sum(r.delivered for r in rs) == sum(r.stations for r in rs)
    assert sum(r.airtime for r in coded) < 0.8 * sum(r.airtime for r in uncoded)


class FakeTnc:
    """Stands in for a TNC with one other station on a perfect channel."""

    def __init__(self, peer: Station) -> None:
        self.peer = peer
        self.t = 0.0
        self.reader = KissReader()

    def clock(self) -> float:
        return self.t

    def send(self, data: bytes) -> None:
        for frame in self.reader.feed(data):
            src, info = parse_ui(frame) or ("", b"")
            self.peer.receive(info, src, self.t)

    def recv(self) -> bytes:
        self.t += 0.25
        if self.t > 3000:
            raise ConnectionError("done")
        d = self.peer.due()
        if d is not None and d <= self.t and (info := self.peer.transmit(self.t)):
            return kiss_wrap(ui_frame(self.peer.call, info))
        return b""


def test_node_loop_speaks_kiss_both_ways(tmp_path: Path) -> None:
    a = Station("N0AAA", Params(), random.Random(1))
    b = Station("N0BBB-7", Params(), random.Random(2))
    sent_by_a = a.originate(b"over the air" * 30, 0.0)
    sent_by_b = b.originate(b"and back" * 30, 0.0)
    tnc = FakeTnc(b)
    log = tmp_path / "frames.log"
    with pytest.raises(ConnectionError):
        run(a, tnc, lambda n: 1.5, tnc.clock, log=FrameLog(log))
    assert b.delivered[sent_by_a].envelope.body == b"over the air" * 30
    assert a.delivered[sent_by_b].envelope.originator == "N0BBB-7"
    # the log alone is enough to recover everything the node sent and heard
    bodies = {d.envelope.body for d in replay(log)}
    assert bodies == {b"over the air" * 30, b"and back" * 30}


def test_blocklist_picks_up_new_ids_when_the_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "blocked.txt"
    blocklist = Blocklist(path)
    assert blocklist.poll() == set()
    path.write_text("0011223344556677  # spam\nnot an id\n")
    assert blocklist.poll() == {bytes.fromhex("0011223344556677")}
    assert blocklist.poll() == set()


class Talker:
    """Sends the given frames at fixed times and records what it hears."""

    def __init__(self, call: str, sends: list[float]) -> None:
        self.call = call
        self.sends = sends
        self.heard: list[tuple[str, float]] = []

    @property
    def done_at(self) -> float | None:
        return None

    def receive(self, frame: bytes, src: str, now: float) -> None:
        self.heard.append((src, now))

    def due(self) -> float | None:
        return self.sends[0] if self.sends else None

    def transmit(self, now: float) -> bytes | None:
        self.sends.pop(0)
        return bytes(100)


def on_air(*sends: list[float]) -> list[Talker]:
    """Talkers all in range of each other and of a listener, on a lossless channel."""
    talkers = [Talker(f"N0T{i}", s) for i, s in enumerate(sends)]
    listener = Talker("N0LSN", [])
    nodes = [*talkers, listener]
    pos = [(0.1 * i, 0.0) for i in range(len(nodes))]
    channel("test", list(nodes), Scenario(loss=0.0), pos, random.Random(1))
    return nodes


def test_stations_keying_up_together_collide() -> None:
    *_, listener = on_air([0.0], [0.05])
    assert listener.heard == []


def test_later_station_hears_the_first_and_waits() -> None:
    a, b, listener = on_air([0.0], [0.5])
    assert [src for src, _ in listener.heard] == ["N0T0", "N0T1"]
    assert b.heard and a.heard, "neither may transmit over the other"


def test_uncoded_resends_exactly_what_a_status_shows_missing() -> None:
    params = Params(backoff=0.1, push_extra=0)
    a = UncodedNode("N0AAA", [3], params, random.Random(1))
    b = UncodedNode("N0BBB", [3], params, random.Random(2))
    a.originate([b"a" * 16, b"b" * 16, b"c" * 16], 0.0)
    pushed = [a.transmit(a.due() or 0.0) or b"" for _ in range(3)]
    b.receive(pushed[0], "N0AAA", 1.0)
    b.receive(pushed[2], "N0AAA", 1.0)
    t = b.due() or 0.0
    a.receive(b.transmit(t) or b"", "N0BBB", t)
    resent = a.transmit(a.due() or 0.0) or b""
    assert int.from_bytes(resent[18:20], "big") == 1
