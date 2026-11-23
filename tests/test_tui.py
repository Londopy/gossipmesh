import asyncio
import os
import random
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import DataTable, RichLog, Static, Switch, TabbedContent, TextArea

from gossipmesh import Params, Station
from gossipmesh._ax25 import KissReader, kiss_wrap, parse_ui, ui_frame
from gossipmesh._monitor import Monitor
from gossipmesh._node import Blocklist, Outbox, run
from gossipmesh._tui import NodeApp, progress, system_is_dark

FAST = Params(backoff=0.05, quiet=2.0, window=2.0)


def airtime(n: int) -> float:
    return 0.3 + (n + 20) * 8 / 1200


def monitor_for(station: Station, blocklist: Blocklist | None = None) -> Monitor:
    m = Monitor(
        station, lambda body, now: station.originate(body, now), airtime, blocklist=blocklist
    )
    station.on_deliver = m.delivered
    return m


def test_frames_count_airtime_neighbours_and_duty() -> None:
    m = monitor_for(Station("N0AAA", FAST))
    m.write(100.0, "tx", "N0AAA", b"\x11" + bytes(150))
    m.write(101.0, "rx", "N0BBB", b"\x13" + bytes(19))
    m.write(102.0, "rx", "N0BBB", b"\x11" + bytes(150))
    m.tick(103.0)
    snap = m.snapshot()
    assert (snap.tx_frames, snap.rx_frames) == (1, 2)
    assert snap.tx_airtime == pytest.approx(airtime(151))
    assert [(n.call, n.frames, n.last) for n in snap.neighbours] == [("N0BBB", 2, 102.0)]
    assert snap.duty == pytest.approx(airtime(151) / 600)
    m.tick(800.0)
    assert m.snapshot().duty == 0.0, "duty only counts the last 10 minutes"


def test_commands_wait_for_the_node_thread() -> None:
    station = Station("N0AAA", FAST)
    m = monitor_for(station)
    m.send_text("net at 8")
    assert station.messages() == [], "nothing happens until the node loop ticks"
    m.tick(1000.0)
    snap = m.snapshot()
    assert len(snap.sent) == 1 and snap.notice.startswith("Sent ")
    assert [(s.held, s.total, s.originated) for s in snap.messages] == [(1, 1, True)]


def test_send_reports_failures_instead_of_raising(tmp_path: Path) -> None:
    m = monitor_for(Station("N0AAA", FAST))
    m.send_text("x" * 70_000)
    m.tick(1000.0)
    first = m.snapshot()
    assert first.notice.startswith("Not sent: message is")
    m.send_file(tmp_path / "missing.txt")
    m.tick(1001.0)
    snap = m.snapshot()
    assert snap.notice.startswith("Could not read")
    assert snap.notice_count == first.notice_count + 1, "each failure is a new notice"
    assert snap.sent == ()
    assert any("Could not read" in e for e in snap.events), "failures go to the log too"


def test_outbox_files_a_message_it_cannot_send_under_failed(tmp_path: Path) -> None:
    m = monitor_for(Station("N0AAA", FAST))
    (tmp_path / "big.txt").write_bytes(b"x" * 70_000)
    os.utime(tmp_path / "big.txt", (0, 0))
    Outbox(tmp_path, lambda body, now: m.send_now(body, now, "outbox"), say=m.say).poll(100.0)
    assert [f.name for f in (tmp_path / "failed").iterdir()] == ["100-big.txt"]
    assert not (tmp_path / "sent").exists()


def test_a_hostile_source_never_reaches_the_screen_raw() -> None:
    m = monitor_for(Station("N0AAA", FAST))
    m.write(1.0, "rx", "\x1bc\x1b[2J", b"\x13" + bytes(19))
    m.tick(2.0)
    snap = m.snapshot()
    assert snap.neighbours == ()
    assert "\x1b" not in snap.events[-1] and " - status" in snap.events[-1]


def test_progress_shows_blocks_held_of_total() -> None:
    a, b = Station("N0AAA", FAST, random.Random(1)), Station("N0BBB", FAST, random.Random(2))
    a.originate(bytes(2000), 0.0)
    m = monitor_for(b)
    for _ in range(5):
        b.receive(a.transmit(a.due() or 0.0) or b"", "N0AAA", 1.0)
    m.tick(2.0)
    (state,) = m.snapshot().messages
    assert (state.held, state.total, state.complete) == (5, 16, False)
    assert progress(5, 16) == "[####--------] 5 of 16"


def test_block_without_a_file_acts_on_the_station() -> None:
    station = Station("N0AAA", FAST)
    m = monitor_for(station)
    m.block(bytes(8))
    m.tick(1.0)
    assert m.snapshot().blocked == {bytes(8)}
    m.unblock(bytes(8))
    m.tick(2.0)
    assert m.snapshot().blocked == frozenset()


def test_block_with_a_file_edits_the_file_and_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / "blocked.txt"
    path.write_text("# spam we have seen\n0011223344556677\n")
    m = monitor_for(Station("N0AAA", FAST), blocklist=Blocklist(path))
    m.block(bytes(8))
    m.tick(1.0)
    assert path.read_text().splitlines() == [
        "# spam we have seen",
        "0011223344556677",
        "0000000000000000",
    ]
    m.unblock(bytes.fromhex("0011223344556677"))
    m.tick(2.0)
    assert path.read_text().splitlines() == ["# spam we have seen", "0000000000000000"]


def test_trusted_only_needs_trusted_keys() -> None:
    station = Station("N0AAA", FAST)
    m = monitor_for(station)
    m.set_trusted_only(True)
    m.tick(1.0)
    assert not station.relay_trusted_only
    assert "needs --trust" in m.snapshot().notice
    station.keys = {"N0BBB": bytes(32)}
    m.set_trusted_only(True)
    m.tick(2.0)
    assert station.relay_trusted_only and m.snapshot().trusted_only


@pytest.mark.parametrize(("fgbg", "dark"), [("15;0", True), ("0;15", False), ("7;default;0", True)])
def test_terminal_background_decides_light_or_dark(
    monkeypatch: pytest.MonkeyPatch, fgbg: str, dark: bool
) -> None:
    monkeypatch.setenv("COLORFGBG", fgbg)
    assert system_is_dark() is dark


class PeerLink:
    """A TNC with one other station on a perfect channel, in real time."""

    def __init__(self, peer: Station) -> None:
        self.peer = peer
        self.reader = KissReader()

    def send(self, data: bytes) -> None:
        for frame in self.reader.feed(data):
            src, info = parse_ui(frame) or ("", b"")
            self.peer.receive(info, src, time.time())

    def recv(self) -> bytes:
        time.sleep(0.01)
        now = time.time()
        d = self.peer.due()
        if d is not None and d <= now and (info := self.peer.transmit(now)):
            return kiss_wrap(ui_frame(self.peer.call, info))
        return b""


def node_app(me: Station, peer: Station) -> tuple[NodeApp, Monitor]:
    m = monitor_for(me)

    def start(stop: threading.Event) -> None:
        m.set_state("connected")
        run(me, PeerLink(peer), airtime, log=m, tick=m.tick, stop=stop, say=m.say)

    return NodeApp(m, start, "test", ["No blocklist file"], dark=True), m


def test_a_new_loop_starts_from_what_the_station_already_blocks(tmp_path: Path) -> None:
    station = Station("N0AAA", FAST)
    station.block(bytes(8))
    (tmp_path / "blocked.txt").write_text("")

    class Quiet:
        def __init__(self) -> None:
            self.reads = 0

        def send(self, data: bytes) -> None:
            pass

        def recv(self) -> bytes:
            self.reads += 1
            if self.reads > 2:
                raise ConnectionError("done")
            return b""

    # the reconnect case: the station blocked an id, and the file no longer lists it
    with pytest.raises(ConnectionError):
        run(station, Quiet(), airtime, blocklist=Blocklist(tmp_path / "blocked.txt"), say=print)
    assert station.blocked == frozenset()


async def wait_for(pilot: Pilot[None], check: Callable[[], object], seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out"
        await pilot.pause(0.1)


def text_of(app: NodeApp, selector: str) -> str:
    return str(app.query_one(selector, Static).render())


def row_keys(app: NodeApp, selector: str) -> list[str]:
    return [k.value or "" for k in app.query_one(selector, DataTable).rows]


def test_tui_shows_a_received_message_as_plain_text() -> None:
    me, peer = Station("N0AAA", FAST, random.Random(1)), Station("N0BBB", FAST, random.Random(2))
    peer.originate(b"net at 8 [bold]not markup[/bold]", time.time())
    app, m = node_app(me, peer)

    async def go() -> None:
        async with app.run_test(size=(110, 40)) as pilot:
            assert app.query_one("#received-empty").display
            await wait_for(pilot, lambda: row_keys(app, "#received"))
            assert not app.query_one("#received-empty").display
            assert app.selected is None, "a row appearing must not pick a message by itself"
            app.query_one("#received", DataTable).focus()
            await pilot.press("down", "up")
            await wait_for(pilot, lambda: "not markup" in text_of(app, "#detail"))
            assert "[bold]not markup[/bold]" in text_of(app, "#detail")
            cell = app.query_one("#flight", DataTable).get_row_at(0)[1]
            # a plain str cell would be read as markup, and "[####" would vanish from the bar
            assert isinstance(cell, Text) and cell.plain.startswith("[#")

    asyncio.run(go())


def test_tui_sends_typed_text_to_the_peer() -> None:
    me, peer = Station("N0AAA", FAST, random.Random(1)), Station("N0BBB", FAST, random.Random(2))
    app, m = node_app(me, peer)

    async def go() -> None:
        async with app.run_test(size=(110, 40)) as pilot:
            app.query_one("#tabs", TabbedContent).active = "send-tab"
            await wait_for(pilot, lambda: not app.query_one("#send-text").disabled)
            app.query_one("#text", TextArea).text = "hello from the tui"
            await pilot.click("#send-text")
            await wait_for(pilot, lambda: peer.delivered)
            await wait_for(pilot, lambda: app.query_one("#sent", DataTable).row_count == 1)
            await wait_for(pilot, lambda: text_of(app, "#notice").startswith("Sent "))
            await pilot.click("#send-text")
            await wait_for(pilot, lambda: text_of(app, "#notice") == "Type a message first.")
            await pilot.pause(1.2)
            assert text_of(app, "#notice") == "Type a message first.", "the old notice came back"
            app.query_one("#tabs", TabbedContent).active = "log-tab"
            await wait_for(pilot, lambda: app.query_one("#log", RichLog).lines)

    asyncio.run(go())
    assert [d.envelope.body for d in peer.delivered.values()] == [b"hello from the tui"]


def test_tui_shows_connection_errors_and_retries() -> None:
    station = Station("N0AAA", FAST)
    m = monitor_for(station)
    attempts: list[int] = []

    def start(stop: threading.Event) -> None:
        attempts.append(1)
        raise ConnectionError("could not reach the KISS TNC at 127.0.0.1:9: refused")

    app = NodeApp(m, start, "127.0.0.1:9", [], dark=False)

    async def go() -> None:
        async with app.run_test(size=(110, 40)) as pilot:
            await wait_for(pilot, lambda: app.query_one("#failed").display)
            assert "refused" in str(app.query_one("#error").render())
            assert app.query_one("#send-text").disabled
            assert app.query_one("#trusted", Switch).disabled, "no --trust, nothing to switch"
            app.action_retry()
            assert m.snapshot().state == "connecting", "a press shows Connecting at once"
            await wait_for(pilot, lambda: len(attempts) == 2)
            await wait_for(pilot, lambda: app.query_one("#failed").display)
            await pilot.click("#retry")
            await wait_for(pilot, lambda: len(attempts) == 3)

    asyncio.run(go())


def test_long_text_messages_keep_their_text_for_the_view() -> None:
    a, b = Station("N0AAA", FAST, random.Random(1)), Station("N0BBB", FAST, random.Random(2))
    body = ("line of a long bulletin\n" * 100).encode()
    a.originate(body, 0.0)
    m = monitor_for(b)
    t = 0.0
    while not b.delivered:
        t = max(t, a.due() or t)
        if (f := a.transmit(t)) is not None:
            b.receive(f, "N0AAA", t)
        t += 1.0
    m.tick(t)
    (r,) = m.snapshot().received
    assert r.text == body.decode() and len(body) > 500


def test_tui_blocks_and_unblocks_the_message_it_shows() -> None:
    me, peer = Station("N0AAA", FAST, random.Random(1)), Station("N0BBB", FAST, random.Random(2))
    first = peer.originate(b"first", time.time())
    app, m = node_app(me, peer)

    async def go() -> None:
        async with app.run_test(size=(110, 40)) as pilot:
            await wait_for(pilot, lambda: first.hex() in row_keys(app, "#flight"))
            app.query_one("#flight", DataTable).focus()
            await pilot.press("down", "up")
            await wait_for(pilot, lambda: app.selected == first)
            await wait_for(pilot, lambda: not app.query_one("#block").disabled)
            await pilot.click("#block")
            await wait_for(pilot, lambda: first in m.snapshot().blocked)
            await wait_for(pilot, lambda: not app.query_one("#unblock").disabled)
            assert first.hex() in row_keys(app, "#flight"), "a blocked message stays listed"
            assert "is blocked" in text_of(app, "#detail")
            await pilot.click("#unblock")
            await wait_for(pilot, lambda: first not in m.snapshot().blocked)

    asyncio.run(go())


def test_tui_switches_trusted_only_relaying() -> None:
    me, peer = Station("N0AAA", FAST, random.Random(1)), Station("N0BBB", FAST, random.Random(2))
    me.keys = {"N0BBB": bytes(32)}
    app, m = node_app(me, peer)

    async def go() -> None:
        async with app.run_test(size=(110, 40)) as pilot:
            app.query_one("#tabs", TabbedContent).active = "relay-tab"
            switch = app.query_one("#trusted", Switch)
            await wait_for(pilot, lambda: not switch.disabled)
            await pilot.click("#trusted")
            await wait_for(pilot, lambda: m.snapshot().trusted_only)
            await pilot.pause(0.6)
            assert switch.value and "On:" in text_of(app, "#relay-status")
            await pilot.click("#trusted")
            await wait_for(pilot, lambda: not m.snapshot().trusted_only)

    asyncio.run(go())
    assert not me.relay_trusted_only


def test_switch_waits_for_the_node_to_apply_it() -> None:
    station = Station("N0AAA", FAST)
    station.keys = {"N0BBB": bytes(32)}
    m = monitor_for(station)

    def start(stop: threading.Event) -> None:
        # connected, but the node never ticks, so the command is never applied
        m.set_state("connected")
        stop.wait()

    app = NodeApp(m, start, "test", [], dark=True)

    async def go() -> None:
        async with app.run_test(size=(110, 40)) as pilot:
            app.query_one("#tabs", TabbedContent).active = "relay-tab"
            switch = app.query_one("#trusted", Switch)
            await wait_for(pilot, lambda: not switch.disabled)
            await pilot.click("#trusted")
            await pilot.pause(1.2)
            assert switch.value, "the switch jumped back before the node applied it"

    asyncio.run(go())


def test_cursor_stays_on_the_picked_message_when_a_row_above_goes() -> None:
    me = Station("N0AAA", FAST)
    m = monitor_for(me)
    t0 = time.time()
    senders = [Station(f"N0SN{i}", FAST, random.Random(i)) for i in range(3)]
    short, picked, below = (
        s.originate(body, t0, ttl=ttl)
        for s, body, ttl in zip(senders, (b"gone soon", b"picked", b"below"), (50, 3600, 3600))
    )

    def start(stop: threading.Event) -> None:
        # the test drives the station itself; this thread only keeps the view connected
        m.set_state("connected")
        stop.wait()

    app = NodeApp(m, start, "test", [], dark=True)

    async def go() -> None:
        async with app.run_test(size=(110, 40)) as pilot:
            for s in senders:
                me.receive(s.transmit(s.due() or t0) or b"", s.call, t0 + 1)
            m.tick(t0 + 1)
            await wait_for(pilot, lambda: len(row_keys(app, "#flight")) == 3)
            assert row_keys(app, "#flight") == [short.hex(), picked.hex(), below.hex()]
            table = app.query_one("#flight", DataTable)
            table.focus()
            table.move_cursor(row=1)
            await wait_for(pilot, lambda: app.selected == picked)
            me.transmit(t0 + 100)  # past the short message's expiry, so the station drops it
            m.tick(t0 + 100)
            await wait_for(pilot, lambda: short.hex() not in row_keys(app, "#flight"))
            await pilot.pause(0.6)
            cursor = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            assert cursor == picked.hex() and app.selected == picked

    asyncio.run(go())
