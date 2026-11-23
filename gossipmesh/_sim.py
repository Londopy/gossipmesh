import math
import random
import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ._baselines import FloodNode, RoutedNode, UncodedNode
from ._message import Envelope, layout, split
from ._station import Params, Station

AX25_OVERHEAD = 20
STRATEGIES = ("coded", "uncoded", "flood", "routed")

# frames that carry message data, for counting how many a station hears before it decodes;
# routed forwarding has no entry, since most frames a station hears there are not for it
_DATA: dict[str, Callable[[bytes], bool]] = {
    "coded": lambda f: f[0] & 15 in (1, 2),
    "uncoded": lambda f: f[0] == 1,
    "flood": lambda f: True,
}


class Node(Protocol):
    call: str

    @property
    def done_at(self) -> float | None: ...

    def receive(self, frame: bytes, src: str, now: float) -> None: ...

    def due(self) -> float | None: ...

    def transmit(self, now: float) -> bytes | None: ...


@dataclass
class Scenario:
    """Stations on a square map. Distances are in units of radio range.

    Channel access matches what Direwolf did on the bench: a station sends at once if the
    channel is clear, and only rolls `persist` each `slot` after waiting for it. Carrier detect
    needs `dcd` seconds to notice a transmission, so stations that key up together collide.
    """

    stations: int = 20
    area: float = 3.0
    loss: float = 0.1
    baud: int = 1200
    txdelay: float = 0.3
    slot: float = 0.1
    persist: float = 0.25
    dcd: float = 0.1
    size: int = 10_000
    block: int = 128
    backoff: float = 4.0
    limit: float = 6 * 3600

    def airtime(self, nbytes: int) -> float:
        return self.txdelay + (nbytes + AX25_OVERHEAD) * 8 / self.baud

    def loss_at(self, d: float) -> float:
        # base loss everywhere, rising to halfway between base and 1 at the edge of range
        return self.loss + (1 - self.loss) * 0.5 * max(0.0, (d - 0.6) / 0.4)


@dataclass
class Result:
    strategy: str
    stations: int
    delivered: int
    frames: int
    airtime: float
    times: list[float] = field(default_factory=list)
    last_tx: float = 0.0
    heard: list[float] = field(default_factory=list)

    @property
    def per_delivery(self) -> float:
        return self.airtime / self.delivered if self.delivered else math.inf


class _CodedNode:
    def __init__(self, station: Station) -> None:
        self.station = station
        self.call = station.call
        self.msg_id: bytes | None = None

    @property
    def done_at(self) -> float | None:
        d = self.station.delivered.get(self.msg_id or b"")
        return d.at if d else None

    def receive(self, frame: bytes, src: str, now: float) -> None:
        self.station.receive(frame, src, now)

    def due(self) -> float | None:
        return self.station.due()

    def transmit(self, now: float) -> bytes | None:
        return self.station.transmit(now)


def place(sc: Scenario, rng: random.Random) -> list[tuple[float, float]]:
    """Random positions whose range graph is connected."""
    for _ in range(1000):
        pos = [(rng.uniform(0, sc.area), rng.uniform(0, sc.area)) for _ in range(sc.stations)]
        if len(_reachable(_neighbours(pos), 0)) == sc.stations:
            return pos
    raise ValueError("could not place a connected network; use a smaller area or more stations")


def _neighbours(pos: list[tuple[float, float]]) -> list[list[int]]:
    return [
        [j for j, q in enumerate(pos) if j != i and math.dist(p, q) < 1.0]
        for i, p in enumerate(pos)
    ]


def _reachable(nbrs: list[list[int]], start: int) -> dict[int, int]:
    """Parent of each station on a shortest path tree from start."""
    parent = {start: start}
    todo = deque([start])
    while todo:
        i = todo.popleft()
        for j in nbrs[i]:
            if j not in parent:
                parent[j] = i
                todo.append(j)
    return parent


def _calls(n: int) -> list[str]:
    return [f"SIM{i:02d}" for i in range(n)]


def _build(
    strategy: str, sc: Scenario, pos: list[tuple[float, float]], rng: random.Random
) -> tuple[list[Node], int]:
    """The stations, and how many blocks the message has."""
    calls = _calls(sc.stations)
    body = rng.randbytes(sc.size)
    packed = Envelope(calls[0], int(sc.limit * 2), body).pack()
    blocks = [b for g in split(packed, sc.block) for b in g]
    # no beacons: they only help stations that join late, and every simulated one is there
    params = Params.for_packet_time(
        sc.airtime(sc.block + 40), sc.backoff, block_size=sc.block, beacon=0.0
    )
    if strategy == "coded":
        coded = [_CodedNode(Station(c, params, random.Random(rng.random()))) for c in calls]
        coded[0].msg_id = coded[0].station.originate(body, 0.0, ttl=sc.limit * 2)
        for n in coded[1:]:
            n.msg_id = coded[0].msg_id
        return list(coded), len(blocks)
    if strategy == "uncoded":
        gens = layout(len(packed), sc.block)
        uncoded = [UncodedNode(c, gens, params, random.Random(rng.random())) for c in calls]
        uncoded[0].originate(blocks, 0.0)
        return list(uncoded), len(blocks)
    delay = params.backoff * params.window
    if strategy == "flood":
        flood = [FloodNode(c, len(blocks), delay, random.Random(rng.random())) for c in calls]
        flood[0].originate(blocks, 0.0)
        return list(flood), len(blocks)
    if strategy == "routed":
        nbrs = _neighbours(pos)
        timeout = 2 * sc.airtime(sc.block + 21) + 2 * sc.airtime(21) + 10 * sc.slot
        routed = []
        for i, c in enumerate(calls):
            tree = _reachable(nbrs, i)
            hops = {calls[d]: calls[_first_hop(tree, i, d)] for d in tree if d != i}
            routed.append(RoutedNode(c, len(blocks), hops, timeout, random.Random(rng.random())))
        routed[0].originate(blocks, calls[1:], 0.0)
        return list(routed), len(blocks)
    raise ValueError(f"unknown strategy {strategy!r}; pick from {', '.join(STRATEGIES)}")


def _first_hop(tree: dict[int, int], src: int, dest: int) -> int:
    while tree[dest] != src:
        dest = tree[dest]
    return dest


def run(strategy: str, sc: Scenario, pos: list[tuple[float, float]], rng: random.Random) -> Result:
    """Simulate one message from station 0 with CSMA, collisions and hidden stations."""
    nodes, blocks = _build(strategy, sc, pos, rng)
    return channel(strategy, nodes, sc, pos, rng, blocks)


def channel(
    strategy: str,
    nodes: list[Node],
    sc: Scenario,
    pos: list[tuple[float, float]],
    rng: random.Random,
    blocks: int = 0,
) -> Result:
    """Run already-built stations on the shared channel until they go quiet."""
    n = len(nodes)
    is_data = _DATA.get(strategy)
    heard = [0] * n
    nbrs = _neighbours(pos)
    loss = [[sc.loss_at(math.dist(pos[i], pos[j])) for j in range(n)] for i in range(n)]
    active: list[tuple[int, float, float, bytes]] = []
    recent: list[tuple[int, float, float]] = []
    next_try = [0.0] * n
    busy_until = [0.0] * n
    deferred = [False] * n
    frames, air, last_tx, t = 0, 0.0, 0.0, 0.0

    def refresh(i: int) -> None:
        d = nodes[i].due()
        next_try[i] = math.inf if d is None else max(d, t, busy_until[i])

    while True:
        end = min((a[2] for a in active), default=math.inf)
        # ties go to a random station, not always the lowest index (the originator)
        i = min(range(n), key=lambda j: (next_try[j], rng.random()))
        t = min(end, next_try[i])
        if t == math.inf or t > sc.limit:
            break
        if end <= next_try[i]:
            tx = next(a for a in active if a[2] == end)
            active.remove(tx)
            s, start, stop, frame = tx
            for r in nbrs[s]:
                clash = any(
                    j != s and (j == r or j in nbrs[r]) and b < stop and e > start
                    for j, b, e in recent
                )
                if not clash and rng.random() >= loss[s][r]:
                    if is_data and is_data(frame) and nodes[r].done_at is None:
                        heard[r] += 1
                    nodes[r].receive(frame, nodes[s].call, t)
                    refresh(r)
            refresh(s)
            continue
        due = nodes[i].due()
        if due is None or due > t:
            next_try[i] = math.inf if due is None else due
            deferred[i] = deferred[i] and due is not None
            continue
        sensed = [
            e for j, b, e in recent if (j == i or (j in nbrs[i] and b + sc.dcd <= t)) and b <= t < e
        ]
        if sensed:
            next_try[i] = max(sensed)
            deferred[i] = True
        elif not deferred[i] or rng.random() < sc.persist:
            deferred[i] = False
            sent = nodes[i].transmit(t)
            if sent is None:
                refresh(i)
                if next_try[i] <= t:
                    next_try[i] = t + sc.slot
                continue
            dur = sc.airtime(len(sent))
            active.append((i, t, t + dur, sent))
            recent.append((i, t, t + dur))
            recent = [r for r in recent if r[2] > t - 60]
            busy_until[i] = t + dur
            next_try[i] = t + dur
            frames += 1
            air += dur
            last_tx = t + dur
        else:
            next_try[i] = t + sc.slot
    times = [d for node in nodes[1:] if (d := node.done_at) is not None]
    per_block = []
    if is_data and blocks:
        per_block = [heard[i] / blocks for i in range(1, n) if nodes[i].done_at is not None]
    return Result(strategy, n - 1, len(times), frames, air, times, last_tx, per_block)


def compare(
    sc: Scenario, runs: int, seed: int, strategies: tuple[str, ...] = STRATEGIES
) -> list[list[Result]]:
    """Run each strategy on the same maps. Returns one list of results per strategy."""
    out: list[list[Result]] = [[] for _ in strategies]
    rng = random.Random(seed)
    for _ in range(runs):
        pos = place(sc, rng)
        run_seed = rng.random()
        for k, s in enumerate(strategies):
            out[k].append(run(s, sc, pos, random.Random(run_seed)))
    return out


def report(results: list[list[Result]]) -> str:
    rows = [
        (
            "strategy",
            "delivered",
            "frames",
            "airtime s",
            "air/delivery s",
            "median s",
            "farthest s",
            "quiet at s",
            "heard/block",
        )
    ]
    for rs in results:
        times = [t for r in rs for t in r.times]
        delivered = sum(r.delivered for r in rs)
        stations = sum(r.stations for r in rs)
        rows.append(
            (
                rs[0].strategy,
                f"{delivered}/{stations}",
                f"{statistics.mean(r.frames for r in rs):.0f}",
                f"{statistics.mean(r.airtime for r in rs):.0f}",
                f"{sum(r.airtime for r in rs) / delivered:.1f}" if delivered else "-",
                f"{statistics.median(times):.0f}" if times else "-",
                f"{statistics.mean(max(r.times) for r in rs if r.times):.0f}" if times else "-",
                f"{statistics.mean(r.last_tx for r in rs):.0f}",
                f"{statistics.mean(h):.2f}" if (h := [x for r in rs for x in r.heard]) else "-",
            )
        )
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    return "\n".join("  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in rows)
