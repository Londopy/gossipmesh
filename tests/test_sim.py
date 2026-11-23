import os
import random
from pathlib import Path

import pytest

from gossipmesh import Params, Station
from gossipmesh._ax25 import KissReader, kiss_wrap, parse_ui, ui_frame
from gossipmesh._framelog import FrameLog, replay
from gossipmesh._monitor import short_text as _short_text
from gossipmesh._node import Blocklist, Outbox, run
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
    bodies = {d.envelope.body for d in replay(log).delivered}
    assert bodies == {b"over the air" * 30, b"and back" * 30}


ID = bytes.fromhex("0011223344556677")


def test_blocklist_reports_the_whole_list_each_time_it_changes(tmp_path: Path) -> None:
    path = tmp_path / "blocked.txt"
    blocklist = Blocklist(path)
    assert blocklist.poll() == set()
    path.write_text("0011223344556677  # spam\nnot an id\n")
    assert blocklist.poll() == {ID}
    assert blocklist.poll() is None, "unchanged"
    path.write_text("")
    assert blocklist.poll() == set(), "an emptied file lifts the block"


def test_blocklist_reads_the_encodings_windows_editors_write(tmp_path: Path) -> None:
    path = tmp_path / "blocked.txt"
    path.write_bytes("0011223344556677 # caf\u00e9\r\n".encode("utf-16"))
    assert Blocklist(path).poll() == {ID}
    path.write_bytes(b"\xef\xbb\xbf0011223344556677 # \xff\r\n")
    assert Blocklist(path).poll() == {ID}


def test_node_stops_relaying_a_blocked_message_and_lifts_it(tmp_path: Path) -> None:
    a = Station("N0AAA", Params(), random.Random(1))
    b = Station("N0BBB", Params(), random.Random(2))
    msg_id = b.originate(b"spam" * 40, 0.0)
    path = tmp_path / "blocked.txt"
    path.write_text(msg_id.hex() + "\n")
    log = tmp_path / "frames.log"
    tnc = FakeTnc(b)
    with pytest.raises(ConnectionError):
        run(a, tnc, lambda n: 1.5, tnc.clock, log=FrameLog(log), blocklist=Blocklist(path))
    assert msg_id not in a.delivered
    assert f"block - {msg_id.hex()}" in log.read_text()


def test_decode_skips_bad_lines_and_marks_blocked_messages(tmp_path: Path) -> None:
    a = Station("N0AAA", Params(), random.Random(1))
    log = tmp_path / "frames.log"
    frames = FrameLog(log)
    msg_id = a.originate(b"keep me", 0.0)
    t = 0.0
    while (d := a.due()) is not None and d < 100:
        t = max(t, d)
        if (frame := a.transmit(t)) is not None:
            frames.write(t, "tx", a.call, frame)
    frames.note(t, "block", msg_id)
    with log.open("a") as out:
        out.write("torn line\n12.0 rx N0BBB zz\n")
    found = replay(log)
    assert [d.envelope.body for d in found.delivered] == [b"keep me"]
    assert found.blocked == {msg_id}
    assert found.skipped == 2


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


def test_outbox_sends_each_finished_file_once(tmp_path: Path) -> None:
    sent: list[bytes] = []
    outbox = Outbox(tmp_path, lambda body, now: sent.append(body))
    done, writing = tmp_path / "net.txt", tmp_path / "half.txt"
    done.write_bytes(b"net at 8")
    writing.write_bytes(b"still being wr")
    now = done.stat().st_mtime + 0.5
    os.utime(done, (now - 5, now - 5))
    outbox.poll(now)
    outbox.poll(now)
    assert sent == [b"net at 8"]
    assert not done.exists() and writing.exists()
    assert [f.read_bytes() for f in (tmp_path / "sent").iterdir()] == [b"net at 8"]


def test_short_text_bodies_are_shown_and_binary_is_not() -> None:
    assert _short_text(b"net tonight\nat 8") == "net tonight\nat 8"
    assert _short_text(bytes(range(256))) is None
    assert _short_text(b"x" * 600) is None


def test_simulated_stations_do_not_beacon() -> None:
    sc = Scenario(stations=8, area=2.0, size=2000)
    rng = random.Random(4)
    r = simulate("coded", sc, place(sc, rng), rng)
    # completion statuses repeat for about 23 quiet times; beacons would run to the limit
    assert r.last_tx < max(r.times) + 3600


def test_frame_log_keeps_one_token_per_field_for_hostile_sources(tmp_path: Path) -> None:
    log = tmp_path / "frames.log"
    FrameLog(log).write(1.0, "rx", "N0 EVL\n", b"\x01")
    assert log.read_text().split() == ["1.000", "rx", "-", "01"]


def test_node_sends_what_lands_in_its_outbox(tmp_path: Path) -> None:
    a = Station("N0AAA", Params(), random.Random(1))
    b = Station("N0BBB", Params(), random.Random(2))
    sent: list[bytes] = []

    def send(body: bytes, now: float) -> None:
        sent.append(a.originate(body, now))

    (tmp_path / "net.txt").write_bytes(b"net at 8")
    os.utime(tmp_path / "net.txt", (0, 0))
    tnc = FakeTnc(b)
    with pytest.raises(ConnectionError):
        run(a, tnc, lambda n: 1.5, tnc.clock, outbox=Outbox(tmp_path, send))
    assert b.delivered[sent[0]].envelope.body == b"net at 8"


def test_outbox_moves_a_bad_file_aside_and_sends_the_rest(tmp_path: Path) -> None:
    def send(body: bytes, now: float) -> None:
        if len(body) > 10:
            raise ValueError("message is too big")
        sent.append(body)

    sent: list[bytes] = []
    for name, body in [
        ("a_big.txt", b"x" * 20),
        ("b_ok.txt", b"ok"),
        (".swp", b"no"),
        ("c~", b"no"),
    ]:
        (tmp_path / name).write_bytes(body)
        os.utime(tmp_path / name, (0, 0))
    Outbox(tmp_path, send).poll(100.0)
    assert sent == [b"ok"]
    assert [f.name for f in (tmp_path / "failed").iterdir()] == ["100-a_big.txt"]
    assert (tmp_path / ".swp").exists() and (tmp_path / "c~").exists()


class Listener(Talker):
    """Decodes once it has heard `need` coded data frames."""

    def __init__(self, call: str, need: int) -> None:
        super().__init__(call, [])
        self.need = need
        self.data = 0
        self._done: float | None = None

    @property
    def done_at(self) -> float | None:
        return self._done

    def receive(self, frame: bytes, src: str, now: float) -> None:
        super().receive(frame, src, now)
        if frame[0] & 15 in (1, 2):
            self.data += 1
            if self.data >= self.need and self._done is None:
                self._done = now


class Sender(Talker):
    def __init__(self, call: str, frames: list[tuple[float, int]]) -> None:
        super().__init__(call, [t for t, _ in frames])
        self.kinds = [k for _, k in frames]

    def transmit(self, now: float) -> bytes | None:
        self.sends.pop(0)
        return bytes([0x10 | self.kinds.pop(0)]) + bytes(99)


def test_heard_per_block_counts_data_frames_heard_before_decoding() -> None:
    # sender: a status, two data frames, then two more after the listener has decoded
    sender = Sender("N0SND", [(0, 3), (5, 1), (10, 2), (15, 1), (20, 1)])
    listener, never = Listener("N0LSN", need=2), Listener("N0FAR", need=99)
    nodes = [sender, listener, never]
    pos = [(0.0, 0.0), (0.1, 0.0), (0.2, 0.0)]
    r = channel("coded", list(nodes), Scenario(loss=0.0), pos, random.Random(1), blocks=4)
    assert listener.data == 4
    assert r.heard == [0.5], "2 data frames before decoding, over 4 blocks; N0FAR never decodes"


def test_heard_per_block_skips_frames_lost_to_collisions() -> None:
    a = Sender("N0AAA", [(0, 1), (8, 1)])
    b = Sender("N0BBB", [(0.05, 1)])
    listener = Listener("N0LSN", need=1)
    pos = [(0.0, 0.0), (0.1, 0.0), (0.2, 0.0)]
    r = channel("coded", [a, b, listener], Scenario(loss=0.0), pos, random.Random(1), blocks=1)
    assert r.heard == [1.0]
    assert listener.heard[0][1] > 8, "the first two collided"
