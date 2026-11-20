import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ._coding import Generation, seed_coefficients
from ._message import (
    BadPacket,
    Envelope,
    check_call,
    join,
    message_id,
    sign,
    split,
    verify,
)
from ._wire import MAX_BLOCK, MIN_BLOCK, Coded, Header, Status, decode, encode


@dataclass
class Params:
    """Protocol timing and forwarding knobs. Times are in seconds."""

    block_size: int = 128
    forward: float = 0.0
    push_extra: int = 2
    backoff: float = 6.0
    window: float = 10.0
    quiet: float = 30.0
    neighbour_ttl: float = 600.0
    max_ttl: float = 86400.0
    max_msgs: int = 64
    status_repeats: int = 6
    beacon: float = 600.0

    @classmethod
    def for_packet_time(cls, airtime: float, **kw: Any) -> "Params":
        """Timers scaled to how long one coded packet takes on air."""
        return cls(backoff=4 * airtime, quiet=20 * airtime, **kw)


def jittered(wait: float, rng: random.Random) -> float:
    # stations that heard the same frames would otherwise all time out at the same instant
    return wait * rng.uniform(0.75, 1.25)


@dataclass
class Delivery:
    envelope: Envelope
    at: float
    verified: bool | None


@dataclass
class _Msg:
    header: Header
    gens: list[Generation]
    next_status: float | None
    status_wait: float
    status_left: int
    credit: list[float] = field(default_factory=list)
    ranks: dict[str, list[int]] = field(default_factory=dict)
    heard: dict[str, float] = field(default_factory=dict)
    last_status: float = -math.inf
    originated: bool = False
    beacon_at: float | None = None
    beacon_heard: bool = False
    beacon_skips: int = 0
    trusted: bool = False

    def __post_init__(self) -> None:
        self.credit = [0.0] * len(self.gens)

    def mine(self) -> tuple[int, ...]:
        return tuple(g.rank for g in self.gens)

    @property
    def complete(self) -> bool:
        return all(g.complete for g in self.gens)


class Station:
    """One gossip-mesh station. Feed it frames with receive(), ask it for frames with transmit().

    It does no I/O and never reads the clock: the caller passes `now` in, so the same code runs
    in the simulator and on air.
    """

    def __init__(
        self,
        call: str,
        params: Params | None = None,
        rng: random.Random | None = None,
        keys: dict[str, bytes] | None = None,
        on_deliver: Callable[[Delivery], None] | None = None,
        relay_trusted_only: bool = False,
        listen_only: bool = False,
    ) -> None:
        self.call = check_call(call)
        self.params = params or Params()
        self.rng = rng or random.Random()
        self.keys = keys or {}
        self.on_deliver = on_deliver
        self.relay_trusted_only = relay_trusted_only
        self.listen_only = listen_only
        self.delivered: dict[bytes, Delivery] = {}
        self._msgs: dict[Header, _Msg] = {}
        self._dead: dict[Header, int] = {}
        self._blocked: set[bytes] = set()
        self._coded_at: float | None = None

    def originate(self, body: bytes, now: float, ttl: float = 3600, key: Any = None) -> bytes:
        p = self.params
        if not 0 < ttl <= p.max_ttl:
            raise ValueError(f"ttl must be between 0 and {p.max_ttl:.0f} seconds")
        if not MIN_BLOCK <= p.block_size <= MAX_BLOCK:
            raise ValueError(f"block size must be {MIN_BLOCK} to {MAX_BLOCK} bytes")
        env = Envelope(self.call, int(now + ttl), body)
        if key is not None:
            env = sign(env, key)
        packed = env.pack()
        if len(packed) > 0xFFFF:
            raise ValueError(f"message is {len(packed)} bytes; the limit is 65535")
        msg_id = message_id(packed)
        header = Header(msg_id, env.expiry, len(packed), p.block_size)
        gens = [Generation.from_blocks(b) for b in split(packed, header.block_size)]
        m = _Msg(header, gens, None, p.quiet, 0)
        m.credit = [k + p.push_extra for k in header.gens]
        m.originated = True
        self._arm_beacon(m, now)
        self._msgs[header] = m
        self.delivered[msg_id] = Delivery(env, now, True if key is not None else None)
        self._schedule(now)
        return msg_id

    def block(self, msg_id: bytes) -> None:
        """Stop relaying a message and ignore it from now on."""
        self._blocked.add(msg_id)
        for h in [h for h in self._msgs if h.msg_id == msg_id]:
            del self._msgs[h]

    def unblock(self, msg_id: bytes) -> None:
        self._blocked.discard(msg_id)

    def receive(self, frame: bytes, src: str, now: float) -> None:
        try:
            pkt = decode(frame)
            src = check_call(src)
        except (BadPacket, ValueError):
            return
        h = pkt.header
        if src == self.call or h in self._dead or h.msg_id in self._blocked:
            return
        if not now < h.expiry <= now + self.params.max_ttl:
            return
        m = self._msgs.get(h)
        if m is None:
            self._expire(now)
            if len(self._msgs) >= self.params.max_msgs:
                return
            m = self._msgs[h] = self._fresh_msg(h, now)
        m.heard[src] = now
        theirs = m.ranks.setdefault(src, [0] * len(h.gens))
        if isinstance(pkt, Status):
            theirs[:] = pkt.ranks
            if list(pkt.ranks) == h.gens:
                m.beacon_heard = True
        else:
            theirs[pkt.gen] = pkt.rank
            self._overheard(m, src, pkt.gen, pkt.rank, now)
            self._absorb(m, pkt, now)
        if any(t > r for t, r in zip(theirs, m.mine())):
            self._prompt(m, now, isinstance(pkt, Status))
        self._schedule(now)

    def due(self) -> float | None:
        """Earliest time this station wants the channel, or None if it has nothing to send."""
        if self.listen_only:
            return None
        times = [t for m in self._msgs.values() if (t := self._status_at(m)) is not None]
        times += [m.beacon_at for m in self._msgs.values() if m.beacon_at is not None]
        if self._coded_at is not None:
            times.append(self._coded_at)
        return min(times, default=None)

    def transmit(self, now: float) -> bytes | None:
        """The frame to send now, if any. Call when due() has passed and the channel is free."""
        self._expire(now)
        for m in self._msgs.values():
            at = self._status_at(m)
            if at is not None and at <= now:
                return self._send_status(m, now)
        for m in self._msgs.values():
            if m.beacon_at is not None and m.beacon_at <= now:
                # a forged full-rank status could otherwise silence beacons for good
                skip = m.beacon_heard and m.beacon_skips < 3
                m.beacon_skips = m.beacon_skips + 1 if skip else 0
                self._arm_beacon(m, now)
                if not skip and self._may_relay(m):
                    return encode(Status(m.header, bytes(m.mine())))
        if self._coded_at is None or self._coded_at > now:
            return None
        return self._send_coded(now)

    def _absorb(self, m: _Msg, pkt: Coded, now: float) -> None:
        gen = m.gens[pkt.gen]
        if gen.complete:
            return
        if pkt.vector is not None:
            coeffs = np.frombuffer(pkt.vector, dtype=np.uint8)
        else:
            coeffs = seed_coefficients(m.header.msg_id, pkt.gen, pkt.seed or 0, gen.k)
        if not gen.add(coeffs, np.frombuffer(pkt.payload, dtype=np.uint8)):
            return
        m.credit[pkt.gen] += self.params.forward
        self._arm_status(m, now + jittered(self.params.quiet, self.rng))
        if m.complete:
            self._finish(m, now)

    def _finish(self, m: _Msg, now: float) -> None:
        h = m.header
        packed = join([g.blocks() for g in m.gens], h.length)
        if message_id(packed) != h.msg_id:
            # a bad packet got mixed in; start this message over
            self._msgs[h] = self._fresh_msg(h, now)
            return
        try:
            env = Envelope.unpack(packed)
        except BadPacket:
            env = None
        verified = None
        if env is not None and env.originator in self.keys:
            verified = verify(env, self.keys[env.originator])
        if env is None or env.expiry != h.expiry or verified is False:
            self._dead[h] = h.expiry
            del self._msgs[h]
            return
        # repeated, so a neighbour that missed everything still hears that this exists
        self._arm_status(m, now + self.rng.uniform(0, self.params.backoff * self.params.window))
        self._arm_beacon(m, now)
        # trust belongs to this header: a forged header reusing the id stays untrusted
        m.trusted = verified is True
        d = self.delivered[h.msg_id] = Delivery(env, now, verified)
        if self.on_deliver:
            self.on_deliver(d)

    def _fresh_msg(self, h: Header, now: float) -> _Msg:
        gens = [Generation(k, h.block_size) for k in h.gens]
        p = self.params
        return _Msg(h, gens, now + jittered(p.quiet, self.rng), p.quiet, p.status_repeats)

    def _arm_status(self, m: _Msg, at: float) -> None:
        m.next_status = at
        m.status_wait = self.params.quiet
        m.status_left = self.params.status_repeats

    def _fresh(self, m: _Msg, now: float) -> list[list[int]]:
        ttl = self.params.neighbour_ttl
        return [r for c, r in m.ranks.items() if now - m.heard[c] <= ttl]

    def _need(self, m: _Msg, g: int, now: float) -> int:
        mine = m.gens[g].rank
        return max([0] + [mine - r[g] for r in self._fresh(m, now)])

    def _wanted(self, m: _Msg, g: int, now: float) -> tuple[int, int]:
        if m.gens[g].rank == 0 or not self._may_relay(m):
            return 0, 0
        need = self._need(m, g, now)
        return max(need, int(m.credit[g])), need

    def _may_relay(self, m: _Msg) -> bool:
        return not self.relay_trusted_only or m.originated or m.trusted

    def _overheard(self, m: _Msg, src: str, g: int, rank: int, now: float) -> None:
        # assume neighbours that are behind the sender heard it too; STATUS corrects this later
        for call, r in m.ranks.items():
            if call != src and r[g] < rank and now - m.heard[call] <= self.params.neighbour_ttl:
                r[g] += 1

    def _schedule(self, now: float) -> None:
        if self._coded_at is not None or self.listen_only:
            return
        best = max(
            (
                (*self._wanted(m, g, now), m.originated)
                for m in self._msgs.values()
                for g in range(len(m.gens))
            ),
            default=(0, 0, False),
        )
        wanted, need, originated = best
        if wanted > 0:
            p = self.params
            # the originator's opening push answers nobody, so it goes out back to back
            push = originated and need == 0
            delay = 0.0 if push else p.backoff * self.rng.uniform(0, p.window) / (1 + need)
            self._coded_at = now + delay

    def _send_coded(self, now: float) -> bytes | None:
        choices = [
            (self._wanted(m, g, now), self.rng.random(), m, g)
            for m in self._msgs.values()
            for g in range(len(m.gens))
        ]
        choices = [c for c in choices if c[0][0] > 0]
        if not choices:
            self._coded_at = None
            return None
        _, _, m, g = max(choices, key=lambda c: (c[0], c[1]))
        gen = m.gens[g]
        if gen.complete:
            seed = self.rng.getrandbits(32)
            payload = gen.encode(seed_coefficients(m.header.msg_id, g, seed, gen.k))
            pkt = Coded(m.header, g, gen.rank, payload.tobytes(), seed=seed)
        else:
            vector, payload = gen.recode(self.rng)
            pkt = Coded(m.header, g, gen.rank, payload.tobytes(), vector=vector.tobytes())
        m.credit[g] = max(0.0, m.credit[g] - 1)
        for r in self._fresh(m, now):
            if r[g] < gen.rank:
                r[g] += 1
        self._coded_at = None
        self._schedule(now)
        return encode(pkt)

    def _arm_beacon(self, m: _Msg, now: float) -> None:
        # Trickle-style: announce a complete message once per interval unless a neighbour
        # already did, so a station that comes on air late still learns it exists
        if self.params.beacon > 0:
            m.beacon_at = now + self.params.beacon * self.rng.uniform(0.5, 1.0)
            m.beacon_heard = False

    def _status_at(self, m: _Msg) -> float | None:
        return m.next_status

    def _prompt(self, m: _Msg, now: float, soon: bool) -> None:
        # a neighbour is still around with pieces we lack, so keep asking; answer a status
        # soon, at most every quiet/2 seconds
        if m.complete:
            return
        m.status_left = self.params.status_repeats
        at = now + jittered(m.status_wait, self.rng)
        if soon and now - m.last_status >= self.params.quiet / 2:
            at = now + self.rng.uniform(0, self.params.backoff * self.params.window)
        m.next_status = at if m.next_status is None else min(m.next_status, at)

    def _send_status(self, m: _Msg, now: float) -> bytes:
        m.last_status = now
        m.status_left -= 1
        m.status_wait = min(m.status_wait * 2, self.params.quiet * 8)
        mine = m.mine()
        if m.status_left > 0 or (not m.complete and self._behind(m, mine)):
            m.next_status = now + jittered(m.status_wait, self.rng)
        else:
            m.next_status = None
        return encode(Status(m.header, bytes(mine)))

    def _behind(self, m: _Msg, mine: tuple[int, ...]) -> bool:
        return any(t > r for theirs in m.ranks.values() for t, r in zip(theirs, mine))

    def _expire(self, now: float) -> None:
        for h in [h for h in self._msgs if h.expiry <= now]:
            del self._msgs[h]
        for h in [h for h, e in self._dead.items() if e <= now]:
            del self._dead[h]
