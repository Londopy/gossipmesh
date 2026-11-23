import argparse
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__
from ._message import check_call, load_signing_key
from ._framelog import FrameLog, replay
from ._monitor import Monitor, short_text, signature_note
from ._node import Blocklist, Link, Outbox, SerialLink, TcpLink, run
from ._sim import STRATEGIES, Scenario, compare, report
from ._station import Delivery, Params, Station

if TYPE_CHECKING:
    from ._tui import NodeApp


def _sim(args: argparse.Namespace) -> int:
    sc = Scenario(
        stations=args.stations,
        area=args.area,
        loss=args.loss,
        baud=args.baud,
        txdelay=args.txdelay,
        size=args.size,
        block=args.block,
        backoff=args.backoff,
    )
    strategies = tuple(args.strategy or STRATEGIES)
    print(report(compare(sc, args.runs, args.seed, strategies)))
    return 0


def _call(text: str) -> str:
    try:
        return check_call(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _trust(path: Path) -> dict[str, bytes]:
    keys = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.split("#")[0].strip()
        if not line:
            continue
        try:
            call, hexkey = line.split()
            key = bytes.fromhex(hexkey)
            if len(key) != 32:
                raise ValueError("an Ed25519 public key is 64 hex digits")
            keys[check_call(call)] = key
        except ValueError as e:
            raise SystemExit(f"{path}:{n}: expected 'CALLSIGN public-key-hex' ({e})") from e
    return keys


def _save(d: Delivery, out: Path | None, say: Callable[[str], None]) -> None:
    if out:
        try:
            (out / f"{d.envelope.msg_id.hex()}.bin").write_bytes(d.envelope.body)
        except OSError as e:
            say(f"could not save {d.envelope.msg_id.hex()}: {e}")


def _report(d: Delivery, out: Path | None) -> None:
    env = d.envelope
    print(f"{env.msg_id.hex()} from {env.originator}, {len(env.body)} bytes, {signature_note(d)}")
    text = short_text(env.body)
    if text is not None:
        for line in text.splitlines():
            print("  " + line)
    sys.stdout.flush()
    _save(d, out, lambda s: print(f"gossipmesh: {s}", file=sys.stderr))


@dataclass
class _Setup:
    """What `node` and `tui` share: the station and everything around it."""

    station: Station
    connect: Callable[[], Link]
    where: str
    airtime: Callable[[int], float]
    originate: Callable[[bytes, float], bytes]
    log: FrameLog | None
    blocklist: Blocklist | None
    settings: list[str]


def _setup(args: argparse.Namespace) -> _Setup:
    if args.relay_trusted_only and not args.trust:
        raise SystemExit("--relay-trusted-only needs --trust to know whose messages to relay")
    sc = Scenario(baud=args.baud, txdelay=args.txdelay, block=args.block)
    params = Params.for_packet_time(
        sc.airtime(args.block + 40), block_size=args.block, beacon=args.beacon
    )
    keys = _trust(args.trust) if args.trust else None
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    station = Station(args.call, params, keys=keys, relay_trusted_only=args.relay_trusted_only)
    key = load_signing_key(args.key) if args.key else None

    def connect() -> Link:
        if args.kiss:
            host, _, port = args.kiss.rpartition(":")
            return TcpLink(host or "127.0.0.1", int(port))
        return SerialLink(args.serial, args.serial_baud)

    def originate(body: bytes, now: float) -> bytes:
        return station.originate(body, now, ttl=args.ttl, key=key)

    where = args.kiss or f"{args.serial} at {args.serial_baud} baud"
    settings = [
        f"{args.block}-byte blocks at {args.baud} baud, messages kept {args.ttl:.0f} s",
        f"Beacons every {args.beacon:.0f} s" if args.beacon else "Beacons off",
        f"Signing with {args.key}" if args.key else "Messages sent unsigned",
        f"Trusted keys from {args.trust}" if args.trust else "No trusted keys",
        f"Blocklist file {args.blocklist}"
        if args.blocklist
        else "No blocklist file: blocks last until the node stops",
        f"Frame log {args.log}" if args.log else "No frame log",
        f"Outbox {args.outbox}" if args.outbox else "No outbox folder",
        f"Received messages saved to {args.out}" if args.out else "Received messages not saved",
    ]
    return _Setup(
        station,
        connect,
        where,
        sc.airtime,
        originate,
        FrameLog(args.log) if args.log else None,
        Blocklist(args.blocklist) if args.blocklist else None,
        settings,
    )


def _node(args: argparse.Namespace) -> int:
    s = _setup(args)
    s.station.on_deliver = lambda d: _report(d, args.out)
    link = s.connect()

    def send(body: bytes, now: float, source: str) -> None:
        print(f"{s.originate(body, now).hex()} sent from {source}", flush=True)

    for f in args.send or []:
        send(f.read_bytes(), time.time(), str(f))
    outbox = (
        Outbox(args.outbox, lambda body, now: send(body, now, str(args.outbox)))
        if args.outbox
        else None
    )
    print(f"{s.station.call} listening", flush=True)
    run(s.station, link, s.airtime, log=s.log, blocklist=s.blocklist, outbox=outbox)
    return 0


def _tui(args: argparse.Namespace) -> int:
    _tui_app(args).run()
    return 0


def _tui_app(args: argparse.Namespace) -> "NodeApp":
    try:
        from ._tui import NodeApp
    except ModuleNotFoundError as e:
        if e.name != "textual":
            raise
        raise RuntimeError("the TUI needs the tui extra: pip install gossipmesh[tui]") from e
    s = _setup(args)
    monitor = Monitor(s.station, s.originate, s.airtime, log=s.log, blocklist=s.blocklist)

    def delivered(d: Delivery) -> None:
        monitor.delivered(d)
        _save(d, args.out, monitor.say)

    s.station.on_deliver = delivered
    if s.blocklist:
        s.blocklist.say = monitor.say
    outbox = (
        Outbox(
            args.outbox,
            lambda body, now: monitor.send_now(body, now, str(args.outbox)),
            say=monitor.say,
        )
        if args.outbox
        else None
    )
    for f in args.send or []:
        monitor.send_file(f)

    def start(stop: threading.Event) -> None:
        link = s.connect()
        monitor.set_state("connected")
        run(
            s.station,
            link,
            s.airtime,
            log=monitor,
            blocklist=s.blocklist,
            outbox=outbox,
            tick=monitor.tick,
            stop=stop,
            say=monitor.say,
        )

    return NodeApp(monitor, start, s.where, s.settings)


def _decode(args: argparse.Namespace) -> int:
    keys = _trust(args.trust) if args.trust else None
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    found = replay(args.log, keys)
    for d in found.delivered:
        _report(d, args.out)
        if d.envelope.msg_id in found.blocked:
            print("  (this node had it on its blocklist)")
    if not found.delivered:
        print(f"{args.log} holds no complete message")
    if found.skipped:
        print(f"skipped {found.skipped} unreadable lines")
    return 0


def _keygen(args: argparse.Namespace) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path: Path = args.file
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    try:
        # owner-only where the OS honours the mode, and never over an existing key
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(f"{path} already exists; not overwriting a key") from None
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    print(f"wrote {path}; share this line for other stations' trust files:")
    print(f"{args.call} {public.hex()}")
    return 0


def _node_options(n: argparse.ArgumentParser) -> None:
    n.add_argument("--call", required=True, type=_call, help="your callsign, e.g. N0CALL-1")
    tnc = n.add_mutually_exclusive_group(required=True)
    tnc.add_argument("--kiss", metavar="HOST:PORT", help="KISS over TCP, e.g. 127.0.0.1:8001")
    tnc.add_argument("--serial", metavar="PORT", help="KISS over a serial port, e.g. COM3")
    n.add_argument("--serial-baud", type=int, default=9600)
    n.add_argument("--baud", type=int, default=1200, help="radio data rate, for pacing")
    n.add_argument("--txdelay", type=float, default=0.3)
    n.add_argument("--block", type=int, default=128)
    n.add_argument("--send", type=Path, action="append", metavar="FILE", help="originate FILE")
    n.add_argument(
        "--outbox",
        type=Path,
        metavar="DIR",
        help="send every file dropped into DIR while running, then move it to DIR/sent",
    )
    n.add_argument("--ttl", type=float, default=3600, help="seconds until sent messages expire")
    n.add_argument(
        "--beacon",
        type=float,
        default=600,
        help="seconds between beacons for complete messages, so late joiners get them (0: off)",
    )
    n.add_argument("--key", type=Path, help="Ed25519 private key (PEM) to sign with")
    n.add_argument("--trust", type=Path, help="file of 'CALLSIGN public-key-hex' lines")
    n.add_argument("--out", type=Path, help="directory to save received message bodies in")
    n.add_argument(
        "--log",
        type=Path,
        metavar="FILE",
        help="append every frame sent and heard to FILE (see decode)",
    )
    n.add_argument(
        "--blocklist",
        type=Path,
        metavar="FILE",
        help="message ids to stop relaying, one per line; re-read when the file changes",
    )
    n.add_argument(
        "--relay-trusted-only",
        action="store_true",
        help="relay a message only after decoding it and checking it is signed by a trusted key",
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gossipmesh", description="Network-coded gossip for packet radio."
    )
    p.add_argument("--version", action="version", version=f"gossipmesh {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sim", help="compare coded gossip with flooding and routed forwarding")
    s.add_argument("--stations", type=int, default=20)
    s.add_argument("--area", type=float, default=3.0, help="map side, in units of radio range")
    s.add_argument("--loss", type=float, default=0.1, help="packet loss inside range (0-1)")
    s.add_argument("--baud", type=int, default=1200)
    s.add_argument("--txdelay", type=float, default=0.3, help="seconds of key-up per frame")
    s.add_argument("--size", type=int, default=10_000, help="message body in bytes")
    s.add_argument("--block", type=int, default=128, help="payload bytes per packet")
    s.add_argument(
        "--backoff",
        type=float,
        default=4.0,
        help="random wait before answering a neighbour, in packet airtimes",
    )
    s.add_argument("--runs", type=int, default=5)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--strategy", action="append", choices=STRATEGIES)
    s.set_defaults(func=_sim)

    n = sub.add_parser("node", help="run a station against a KISS TNC")
    _node_options(n)
    n.set_defaults(func=_node)

    t = sub.add_parser("tui", help="run a station with a live view in the terminal")
    _node_options(t)
    t.set_defaults(func=_tui)

    d = sub.add_parser("decode", help="recover the messages in a node's --log file")
    d.add_argument("log", type=Path)
    d.add_argument("--trust", type=Path, help="file of 'CALLSIGN public-key-hex' lines")
    d.add_argument("--out", type=Path, help="directory to save decoded message bodies in")
    d.set_defaults(func=_decode)

    k = sub.add_parser("keygen", help="make an Ed25519 signing key")
    k.add_argument("file", type=Path)
    k.add_argument("--call", required=True, type=_call)
    k.set_defaults(func=_keygen)
    return p


def main(argv: list[str] | None = None) -> int:
    # message text comes off the air; a character the console code page lacks must not
    # crash an unattended node whose output is redirected
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = _parser().parse_args(argv)
    try:
        code: int = args.func(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError) as e:
        print(f"gossipmesh: {e}", file=sys.stderr)
        return 1
    return code
