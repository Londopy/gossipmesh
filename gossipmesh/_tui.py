import dataclasses
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.theme import BUILTIN_THEMES, Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    RichLog,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)

from ._monitor import Monitor, Snapshot

# ANSI colours 0-6 and 8 are the dark ones; COLORFGBG ends with the background's number
_DARK_BACKGROUNDS = {0, 1, 2, 3, 4, 5, 6, 8}


def system_is_dark() -> bool:
    """The terminal's light or dark setting if it says, else the OS's; dark if neither does."""
    bg = os.environ.get("COLORFGBG", "").split(";")[-1]
    if bg.isdigit():
        return int(bg) in _DARK_BACKGROUNDS
    if sys.platform == "win32":
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0)
        except OSError:
            return True
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        return out.stdout.strip() == "Dark"
    return True


def theme(dark: bool) -> Theme:
    # the terminal's own colours, with amber for the parts that are gossipmesh's
    base = BUILTIN_THEMES["ansi-dark" if dark else "ansi-light"]
    accent = "ansi_yellow" if dark else "ansi_red"
    name = "gossipmesh-dark" if dark else "gossipmesh-light"
    return dataclasses.replace(base, name=name, primary=accent, accent=accent)


def progress(held: int, total: int, width: int = 12) -> str:
    filled = round(width * held / total) if total else 0
    return f"[{'#' * filled}{'-' * (width - filled)}] {held} of {total}"


def ago(now: float, then: float) -> str:
    s = max(0, int(now - then))
    if s < 60:
        return f"{s} s ago"
    if s < 3600:
        return f"{s // 60} min ago"
    return f"{s // 3600} h ago"


def sync_rows(
    table: DataTable[Text], rows: Mapping[str, tuple[str, ...]], keep: str | None = None
) -> None:
    """Make the table hold exactly these rows, touching only cells that changed.

    Rows are matched by key, so the cursor stays on the row whose key is `keep`.
    """
    have = {k.value for k in table.rows if k.value is not None}
    for key in have - rows.keys():
        table.remove_row(key)
    columns = list(table.columns)
    for key, cells in rows.items():
        if key not in have:
            table.add_row(*(Text(c) for c in cells), key=key)
            continue
        for column, value in zip(columns, cells):
            old = table.get_cell(key, column)
            if old.plain != value:
                table.update_cell(key, column, Text(value), update_width=len(value) > len(old))
    if keep is not None and keep in rows:
        row = table.get_row_index(keep)
        if table.cursor_row != row:
            table.move_cursor(row=row)


class NodeApp(App[None]):
    """`gossipmesh tui`: a node with a live view of what it is doing."""

    TITLE = "gossipmesh"
    CSS = """
    #banner { height: auto; padding: 0 1; }
    #connecting { height: 3; }
    #connecting LoadingIndicator { width: 6; height: 1; }
    #failed { height: auto; border: round $error; padding: 0 1; }
    #failed Label { width: 1fr; }
    #status { height: 1; padding: 0 1; color: $primary; }
    #notice { height: auto; padding: 0 1; }
    .heading { text-style: bold; color: $primary; margin-top: 1; }
    .empty { color: $text-muted; padding: 0 1; }
    DataTable { height: auto; max-height: 12; }
    #detail-box { border: round $primary; padding: 0 1; height: auto; max-height: 14; }
    #text { height: 6; }
    .row { height: auto; margin-top: 1; }
    .row Input { width: 1fr; }
    #relay-status { margin-top: 1; }
    #trusted-row { height: auto; }
    #trusted-row Label { padding: 1 1; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f5", "retry", "Reconnect"),
    ]

    def __init__(
        self,
        monitor: Monitor,
        start: Callable[[threading.Event], None],
        where: str,
        settings: list[str],
        dark: bool | None = None,
    ) -> None:
        super().__init__()
        self.monitor = monitor
        self.start = start
        self.where = where
        self.settings = settings
        self.dark = system_is_dark() if dark is None else dark
        # read once here: the node thread owns the station from now on
        self.has_keys = bool(monitor.station.keys)
        self.stop = threading.Event()
        self.selected: bytes | None = None
        self.shown_detail = ""
        self.logged = 0
        self.notices_seen = 0
        self.wanted_trusted: bool | None = None
        self.sub_title = f"{monitor.station.call} on {where}"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="banner"):
            with Horizontal(id="connecting"):
                yield LoadingIndicator()
                yield Label(Text(f"Connecting to the TNC at {self.where}..."))
            with Horizontal(id="failed"):
                yield Label("", id="error")
                yield Button("Reconnect", id="retry", variant="primary")
        yield Static("", id="status")
        yield Static("", id="notice")
        with TabbedContent(id="tabs"):
            with TabPane("Messages", id="messages-tab"):
                yield Label("In flight", classes="heading")
                yield DataTable(id="flight", cursor_type="row")
                yield Static(
                    "Nothing in flight. Messages heard on the air show up here, with how many "
                    "of their blocks have arrived.",
                    id="flight-empty",
                    classes="empty",
                )
                yield Label("Received", classes="heading")
                yield DataTable(id="received", cursor_type="row")
                yield Static("No messages decoded yet.", id="received-empty", classes="empty")
                with VerticalScroll(id="detail-box"):
                    yield Static("Pick a message to see it here.", id="detail")
                with Horizontal(classes="row"):
                    yield Button("Block this message", id="block", disabled=True)
                    yield Button("Unblock", id="unblock", disabled=True)
            with TabPane("Send", id="send-tab"):
                yield Label("Message text", classes="heading")
                yield TextArea(id="text")
                yield Button("Send text", id="send-text", variant="primary")
                with Horizontal(classes="row"):
                    yield Input(placeholder="Path to a file to send", id="path")
                    yield Button("Send file", id="send-file")
                yield Label("Sent from this node", classes="heading")
                yield DataTable(id="sent", cursor_type="row")
                yield Static("Nothing sent yet.", id="sent-empty", classes="empty")
            with TabPane("Neighbours", id="neighbours-tab"):
                yield DataTable(id="neighbours", cursor_type="row")
                yield Static(
                    "No stations heard yet. Every station whose frames reach this one is "
                    "listed here.",
                    id="neighbours-empty",
                    classes="empty",
                )
            with TabPane("Log", id="log-tab"):
                yield RichLog(id="log", wrap=True, markup=False, max_lines=1000)
            with TabPane("Relay", id="relay-tab"):
                with Horizontal(id="trusted-row"):
                    yield Switch(id="trusted", disabled=True)
                    yield Label("Relay only messages signed by a trusted key")
                yield Static(
                    "Start with --trust to choose whose messages to relay."
                    if not self.has_keys
                    else "Off: this node relays every message it hears.",
                    id="relay-status",
                )
                yield Label("Settings", classes="heading")
                yield Static(Text("\n".join(self.settings)), id="settings")
                yield Label("Blocked messages", classes="heading")
                yield Static("None.", id="blocked")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(theme(self.dark))
        self.theme = theme(self.dark).name
        self.query_one("#flight", DataTable).add_columns("Message", "Progress", "State")
        self.query_one("#received", DataTable).add_columns("Time", "From", "Size", "Signature")
        self.query_one("#sent", DataTable).add_columns("Time", "Message", "From")
        self.query_one("#neighbours", DataTable).add_columns("Station", "Last heard", "Frames")
        self.run_node()
        self.refresh_view()
        self.set_interval(0.5, self.refresh_view)

    @work(thread=True, exclusive=True)
    def run_node(self) -> None:
        try:
            self.start(self.stop)
        except (OSError, RuntimeError, ValueError) as e:
            self.monitor.set_state("error", str(e))
        else:
            self.monitor.set_state("stopped")

    def action_retry(self) -> None:
        if self.monitor.snapshot().state == "error":
            # set before the worker starts, so a second press cannot start a second loop
            self.monitor.set_state("connecting")
            self.run_node()

    def on_unmount(self) -> None:
        # the node loop checks this between reads, which time out every 0.2 s
        self.stop.set()

    def connected(self) -> bool:
        return self.monitor.snapshot().state == "connected"

    def notify_user(self, text: str) -> None:
        self.query_one("#notice", Static).update(Text(text))

    def refresh_view(self) -> None:
        try:
            self.show(self.monitor.snapshot())
        except NoMatches:
            # the refresh timer can fire once more while the app is closing and its widgets go
            if self.is_running:
                raise

    def show(self, snap: Snapshot) -> None:
        connected = snap.state == "connected"
        self.query_one("#connecting").display = snap.state == "connecting"
        self.query_one("#failed").display = snap.state == "error"
        self.query_one("#error", Label).update(Text(f"Not connected: {snap.detail}"))
        self.query_one("#status", Static).update(Text(self.status_line(snap)))
        if snap.notice_count != self.notices_seen:
            self.notices_seen = snap.notice_count
            self.notify_user(snap.notice)
        for button in ("#send-text", "#send-file"):
            self.query_one(button, Button).disabled = not connected
        self.refresh_messages(snap, connected)
        self.refresh_send(snap)
        self.refresh_neighbours(snap)
        self.refresh_log(snap)
        self.refresh_relay(snap, connected)

    def status_line(self, snap: Snapshot) -> str:
        if snap.state == "connecting":
            return "Connecting..."
        if snap.state == "error":
            return "Not connected. Press F5 or Reconnect to try again."
        if snap.state == "stopped":
            return "Stopped."
        return (
            f"Sent {snap.tx_frames} frames, {snap.tx_airtime:.0f} s on air. "
            f"Heard {snap.rx_frames} frames, {snap.rx_airtime:.0f} s. "
            f"Transmitting {snap.duty:.1%} of the last 10 min."
        )

    def refresh_messages(self, snap: Snapshot, connected: bool) -> None:
        senders = {r.msg_id: r.originator for r in snap.received}
        rows = {}
        for m in snap.messages:
            if m.originated:
                state = "sent by this node"
            elif m.complete:
                state = f"decoded, from {senders.get(m.msg_id, '?')}"
            else:
                state = "arriving"
            rows[m.msg_id.hex()] = (m.msg_id.hex(), progress(m.held, m.total), state)
        # a blocked message is dropped from the station, but stays here so it can be unblocked
        for msg_id in snap.blocked:
            rows[msg_id.hex()] = (msg_id.hex(), "-", "blocked")
        keep = self.selected.hex() if self.selected else None
        flight = self.query_one("#flight", DataTable)
        sync_rows(flight, rows, keep)
        flight.display = bool(rows)
        self.query_one("#flight-empty").display = not rows
        received = self.query_one("#received", DataTable)
        sync_rows(
            received,
            {
                r.msg_id.hex(): (
                    time.strftime("%H:%M:%S", time.localtime(r.at)),
                    r.originator,
                    f"{r.size} bytes",
                    r.signature,
                )
                for r in snap.received
            },
            keep,
        )
        received.display = bool(snap.received)
        self.query_one("#received-empty").display = not snap.received
        detail = self.detail(snap)
        if detail != self.shown_detail:
            # message text comes off the air: never let it be read as markup
            self.query_one("#detail", Static).update(Text(detail))
            self.shown_detail = detail
        selected = self.selected
        self.query_one("#block", Button).disabled = not (
            connected and selected is not None and selected not in snap.blocked
        )
        self.query_one("#unblock", Button).disabled = not (
            connected and selected is not None and selected in snap.blocked
        )

    def detail(self, snap: Snapshot) -> str:
        if self.selected is None:
            return "Pick a message to see it here."
        if self.selected in snap.blocked:
            return f"{self.selected.hex()} is blocked: this node ignores it and does not relay it."
        for r in snap.received:
            if r.msg_id == self.selected:
                body = r.text if r.text is not None else f"({r.size} bytes that are not text)"
                return f"{r.msg_id.hex()} from {r.originator}, {r.signature}\n\n{body}"
        for m in snap.messages:
            if m.msg_id == self.selected:
                return f"{m.msg_id.hex()}: {m.held} of {m.total} blocks so far."
        return f"{self.selected.hex()} is no longer held: it has expired."

    def refresh_send(self, snap: Snapshot) -> None:
        sent = self.query_one("#sent", DataTable)
        sync_rows(
            sent,
            {
                s.msg_id.hex(): (
                    time.strftime("%H:%M:%S", time.localtime(s.at)),
                    s.msg_id.hex(),
                    s.source,
                )
                for s in snap.sent
            },
        )
        sent.display = bool(snap.sent)
        self.query_one("#sent-empty").display = not snap.sent

    def refresh_neighbours(self, snap: Snapshot) -> None:
        table = self.query_one("#neighbours", DataTable)
        sync_rows(
            table,
            {n.call: (n.call, ago(snap.now, n.last), str(n.frames)) for n in snap.neighbours},
        )
        table.display = bool(snap.neighbours)
        self.query_one("#neighbours-empty").display = not snap.neighbours

    def refresh_log(self, snap: Snapshot) -> None:
        # the monitor keeps the last 500 events; write the ones that arrived since last time
        new = min(snap.event_count - self.logged, len(snap.events))
        log = self.query_one("#log", RichLog)
        for line in snap.events[len(snap.events) - new :] if new > 0 else ():
            log.write(line)
        self.logged = snap.event_count

    def refresh_relay(self, snap: Snapshot, connected: bool) -> None:
        switch = self.query_one("#trusted", Switch)
        switch.disabled = not (connected and self.has_keys)
        if self.wanted_trusted == snap.trusted_only:
            self.wanted_trusted = None
        # leave a flip the node has not applied yet alone, so the switch does not jump back
        if self.wanted_trusted is None and switch.value != snap.trusted_only:
            with switch.prevent(Switch.Changed):
                switch.value = snap.trusted_only
        if self.has_keys:
            self.query_one("#relay-status", Static).update(
                "On: messages are passed on only after they decode and their signature checks "
                "out against a trusted key."
                if snap.trusted_only
                else "Off: this node relays every message it hears."
            )
        self.query_one("#blocked", Static).update(
            "\n".join(sorted(m.hex() for m in snap.blocked)) or "None."
        )

    @on(DataTable.RowHighlighted, "#flight, #received")
    def pick(self, event: DataTable.RowHighlighted) -> None:
        # rows added or moved by a refresh also fire this; only a person's choice counts
        if event.data_table.has_focus:
            self.pick_row(event.row_key.value)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        # moving into a table picks the row its cursor is already on
        table = event.widget
        if isinstance(table, DataTable) and table.id in ("flight", "received") and table.row_count:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            self.pick_row(key)

    def pick_row(self, key: str | None) -> None:
        if key is not None:
            self.selected = bytes.fromhex(key)
            self.refresh_view()

    @on(Button.Pressed, "#retry")
    def retry(self) -> None:
        self.action_retry()

    @on(Button.Pressed, "#block")
    def block(self) -> None:
        if self.selected is not None and self.connected():
            self.monitor.block(self.selected)

    @on(Button.Pressed, "#unblock")
    def unblock(self) -> None:
        if self.selected is not None and self.connected():
            self.monitor.unblock(self.selected)

    @on(Button.Pressed, "#send-text")
    def send_text(self) -> None:
        if not self.connected():
            self.notify_user("Not connected to the TNC, so nothing can be sent.")
            return
        area = self.query_one("#text", TextArea)
        if not area.text.strip():
            self.notify_user("Type a message first.")
            return
        self.monitor.send_text(area.text)
        area.clear()
        self.notify_user("Sending...")

    @on(Button.Pressed, "#send-file")
    @on(Input.Submitted, "#path")
    def send_file(self) -> None:
        if not self.connected():
            self.notify_user("Not connected to the TNC, so nothing can be sent.")
            return
        field = self.query_one("#path", Input)
        if not field.value.strip():
            self.notify_user("Give the path of a file first.")
            return
        self.monitor.send_file(Path(field.value.strip()).expanduser())
        field.value = ""
        self.notify_user("Sending...")

    @on(Switch.Changed, "#trusted")
    def trusted(self, event: Switch.Changed) -> None:
        self.wanted_trusted = event.value
        self.monitor.set_trusted_only(event.value)
