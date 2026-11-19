import random

import pytest

from gossipmesh import Params, Station
from gossipmesh._ax25 import KissReader, kiss_wrap, parse_ui, ui_frame
from gossipmesh._node import run
from gossipmesh._sim import Scenario, compare, place
from gossipmesh._sim import run as simulate


def test_coded_reaches_every_station_on_a_small_map() -> None:
    sc = Scenario(stations=8, area=2.0, size=2000)
    rng = random.Random(4)
    r = simulate("coded", sc, place(sc, rng), rng)
    assert r.delivered == 7
    assert r.last_tx < sc.limit, "stations kept transmitting until the time limit"


@pytest.mark.slow
def test_coded_beats_flooding_on_airtime_per_delivery() -> None:
    coded, flood = compare(Scenario(), runs=3, seed=1, strategies=("coded", "flood"))
    air = [
        sum(r.airtime for r in rs) / max(1, sum(r.delivered for r in rs)) for rs in (coded, flood)
    ]
    assert sum(r.delivered for r in coded) == sum(r.stations for r in coded)
    assert air[0] < air[1]


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


def test_node_loop_speaks_kiss_both_ways() -> None:
    a = Station("N0AAA", Params(), random.Random(1))
    b = Station("N0BBB-7", Params(), random.Random(2))
    sent_by_a = a.originate(b"over the air" * 30, 0.0)
    sent_by_b = b.originate(b"and back" * 30, 0.0)
    tnc = FakeTnc(b)
    with pytest.raises(ConnectionError):
        run(a, tnc, lambda n: 1.5, tnc.clock)
    assert b.delivered[sent_by_a].envelope.body == b"over the air" * 30
    assert a.delivered[sent_by_b].envelope.originator == "N0BBB-7"
