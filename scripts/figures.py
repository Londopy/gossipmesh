"""Reproduce the figures quoted in the README.

    python scripts/figures.py decode
    python scripts/figures.py flood
    python scripts/figures.py backoff
    python scripts/figures.py vectors

Every run is seeded, so the same command prints the same numbers. The simulator ones take
a few minutes each.
"""

import argparse
import random
import statistics
from collections import Counter

from gossipmesh import Generation, seed_coefficients
from gossipmesh._sim import Node, Result, Scenario, _build, channel, compare, place
from gossipmesh._wire import SEEDED, VECTOR

SEED_BYTES = 4


def decode(args: argparse.Namespace) -> None:
    """Extra packets needed to decode a generation from random seeded packets."""
    rng = random.Random(args.seed)
    print("| Blocks | Generations | Needed 1 extra | Needed 2 or more | Mean extra |")
    print("|---|---|---|---|---|")
    for k in (8, 16, 32):
        extra: Counter[int] = Counter()
        for _ in range(args.generations):
            src = Generation.from_blocks([rng.randbytes(16) for _ in range(k)])
            dst = Generation(k, 16)
            sent = 0
            while not dst.complete:
                c = seed_coefficients(bytes(8), 0, rng.getrandbits(32), k)
                dst.add(c, src.encode(c))
                sent += 1
            extra[sent - k] += 1
        n = args.generations
        more = sum(c for e, c in extra.items() if e >= 2)
        mean = sum(e * c for e, c in extra.items()) / n
        print(f"| {k} | {n} | {extra[1] / n:.2%} | {more / n:.2%} | {mean:.4f} |")


def _cell(results: list[Result]) -> str:
    delivered = sum(r.delivered for r in results)
    stations = sum(r.stations for r in results)
    if not delivered:
        return "none"
    air = sum(r.airtime for r in results) / delivered
    return f"{air:,.1f} s ({delivered / stations:.0%})"


def flood(args: argparse.Namespace) -> None:
    """Airtime per station reached, coded gossip against plain flooding."""
    losses = (0.0, 0.02, 0.05, 0.1)
    print("| Message | " + " | ".join(f"`--loss {x:g}`" for x in losses) + " |")
    print("|---|" + "---|" * len(losses))
    for size in (500, 2000, 10_000):
        cells: dict[str, list[str]] = {"coded": [], "flood": []}
        for loss in losses:
            coded, flooded = compare(
                Scenario(loss=loss, size=size), args.runs, args.seed, ("coded", "flood")
            )
            cells["coded"].append(_cell(coded))
            cells["flood"].append(_cell(flooded))
        for strategy, row in cells.items():
            print(f"| {size:,} bytes, {strategy} | " + " | ".join(row) + " |", flush=True)


def backoff(args: argparse.Namespace) -> None:
    """Coded against uncoded airtime and farthest decode, over a range of back-offs."""
    for area in (3.0, 4.0):
        print(f"\n`--area {area:g}`, {args.runs} runs\n")
        print(
            "| Back-off | Coded airtime | Uncoded airtime | Coded / uncoded | Farthest, coded vs uncoded |"
        )
        print("|---|---|---|---|---|")
        for factor in (0.4, 1, 2, 4, 8, 16):
            sc = Scenario(area=area, backoff=factor)
            coded, uncoded = compare(sc, args.runs, args.seed, ("coded", "uncoded"))
            air = [statistics.mean(r.airtime for r in rs) for rs in (coded, uncoded)]
            far = [statistics.mean(max(r.times) for r in rs if r.times) for rs in (coded, uncoded)]
            print(
                f"| {factor:g} | {air[0]:,.0f} s | {air[1]:,.0f} s | {air[0] / air[1]:.0%} "
                f"| {far[0]:,.0f} s vs {far[1]:,.0f} s |",
                flush=True,
            )


class _Counting:
    """Wraps a simulated station to add up airtime, and what its vectors cost over a seed."""

    def __init__(self, node: Node, sc: Scenario, air: dict[str, float], frames: Counter[str]):
        self.node, self.sc, self.air, self.frames, self.call = node, sc, air, frames, node.call

    @property
    def done_at(self) -> float | None:
        return self.node.done_at

    def receive(self, frame: bytes, src: str, now: float) -> None:
        self.node.receive(frame, src, now)

    def due(self) -> float | None:
        return self.node.due()

    def transmit(self, now: float) -> bytes | None:
        frame = self.node.transmit(now)
        if frame:
            kind = frame[0] & 15
            air = self.sc.airtime(len(frame))
            self.air["all"] += air
            if kind == VECTOR:
                vector = len(frame) - 19 - self.sc.block
                self.air["vector"] += air - self.sc.airtime(len(frame) - vector + SEED_BYTES)
            self.frames[{SEEDED: "seeded", VECTOR: "vectors"}.get(kind, "status")] += 1
        return frame


def vectors(args: argparse.Namespace) -> None:
    """Share of all airtime spent on coefficient vectors beyond what a seed would cost."""
    sc = Scenario()
    rng = random.Random(args.seed)
    air = {"all": 0.0, "vector": 0.0}
    frames: Counter[str] = Counter()
    for _ in range(args.runs):
        pos = place(sc, rng)
        run_rng = random.Random(rng.random())
        nodes, blocks = _build("coded", sc, pos, run_rng)
        wrapped: list[Node] = [_Counting(n, sc, air, frames) for n in nodes]
        channel("coded", wrapped, sc, pos, run_rng, blocks)
    print(
        f"{args.runs} runs on the default map: {frames['seeded']} seeded packets, "
        f"{frames['vectors']} vector packets, {frames['status']} statuses. Vectors cost "
        f"{air['vector'] / air['all']:.1%} of all airtime beyond a 4-byte seed."
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=1)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode", help=decode.__doc__)
    d.add_argument("--generations", type=int, default=2000)
    d.set_defaults(func=decode)
    for name, func in (("flood", flood), ("backoff", backoff), ("vectors", vectors)):
        s = sub.add_parser(name, help=func.__doc__)
        s.add_argument("--runs", type=int, default=10)
        s.set_defaults(func=func)
    args = p.parse_args()
    args.func(args)


main()
