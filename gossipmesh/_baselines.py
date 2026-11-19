"""Uncoded strategies the simulator compares against. Not part of the protocol."""

import heapq
import math
import random
from collections import Counter, deque
from collections.abc import Iterable

from ._station import Params, jittered

_HEADER = bytes(17)


class FloodNode:
    """Plain flooding: rebroadcast every block not seen before, once, after a random delay."""

    def __init__(self, call: str, nblocks: int, delay: float, rng: random.Random) -> None:
        self.call = call
        self.nblocks = nblocks
        self.delay = delay
        self.rng = rng
        self.done_at: float | None = None
        self._have: set[int] = set()
        self._queue: list[tuple[float, int, bytes]] = []

    def originate(self, blocks: list[bytes], now: float) -> None:
        for i, b in enumerate(blocks):
            self._have.add(i)
            heapq.heappush(self._queue, (now, i, b))
        self.done_at = now

    def receive(self, frame: bytes, src: str, now: float) -> None:
        i = int.from_bytes(frame[17:19], "big")
        if i in self._have:
            return
        self._have.add(i)
        heapq.heappush(self._queue, (now + self.rng.uniform(0, self.delay), i, frame[19:]))
        if len(self._have) == self.nblocks and self.done_at is None:
            self.done_at = now

    def due(self) -> float | None:
        return self._queue[0][0] if self._queue else None

    def transmit(self, now: float) -> bytes | None:
        if not self._queue or self._queue[0][0] > now:
            return None
        _, i, block = heapq.heappop(self._queue)
        return _HEADER + i.to_bytes(2, "big") + block


def _bits(have: Iterable[int], first: int, count: int) -> bytes:
    """Bitmap of blocks first..first+count-1 present in have."""
    out = bytearray((count + 7) // 8)
    for i in have:
        if first <= i < first + count:
            out[(i - first) // 8] |= 1 << ((i - first) % 8)
    return bytes(out)


def _unbits(data: bytes, first: int) -> set[int]:
    return {first + i for i in range(len(data) * 8) if data[i // 8] >> (i % 8) & 1}


class UncodedNode:
    """The coded station with coding switched off, as close to Station as plain blocks allow.

    Blocks are grouped into the same generations. A data frame carries one block plus the
    sender's bitmap for that generation, where a coded packet carries the sender's rank for it,
    and a status carries the bitmap of every generation, where Station's carries every rank.
    The originator pushes k + push_extra frames per generation back to back. Everything else
    uses Station's rules: deficits drive sending and back-off, sends and overheard frames are
    assumed received, and status timers, repeats and the keep-asking rule are the same.
    """

    DATA, STATUS = 1, 2

    def __init__(self, call: str, gens: list[int], params: Params, rng: random.Random) -> None:
        self.call = call
        self.params = params
        self.rng = rng
        self.done_at: float | None = None
        self.nblocks = sum(gens)
        self._firsts = [sum(gens[:g]) for g in range(len(gens))]
        self._sizes = gens
        self._have: dict[int, bytes] = {}
        self._theirs: dict[str, set[int]] = {}
        self._heard: dict[str, float] = {}
        self._push: list[int] = []
        self._fill_at: float | None = None
        self._next_status: float | None = None
        self._status_wait = params.quiet
        self._status_left = 0
        self._last_status = -math.inf

    def originate(self, blocks: list[bytes], now: float) -> None:
        self._have = dict(enumerate(blocks))
        for first, k in zip(self._firsts, self._sizes):
            extra = [first + self.rng.randrange(k) for _ in range(self.params.push_extra)]
            self._push += list(range(first, first + k)) + extra
        self._push.reverse()
        self._fill_at = now
        self.done_at = now

    def receive(self, frame: bytes, src: str, now: float) -> None:
        self._heard[src] = now
        if frame[0] == self.STATUS:
            bitmap = frame[17:]
            theirs: set[int] = set()
            for first, k in zip(self._firsts, self._sizes):
                theirs |= _unbits(bitmap[: (k + 7) // 8], first)
                bitmap = bitmap[(k + 7) // 8 :]
            self._theirs[src] = theirs
        else:
            g, i = frame[17], int.from_bytes(frame[18:20], "big")
            nbytes = (self._sizes[g] + 7) // 8
            theirs = self._theirs.setdefault(src, set())
            theirs -= self._blocks(g)
            theirs |= _unbits(frame[20 : 20 + nbytes], self._firsts[g])
            self._overheard(src, i, now)
            if i not in self._have:
                self._have[i] = frame[20 + nbytes :]
                self._progress(now)
        if self._theirs[src] - self._have.keys():
            self._prompt(now, frame[0] == self.STATUS)
        self._schedule(now)

    def due(self) -> float | None:
        return min((t for t in (self._fill_at, self._next_status) if t is not None), default=None)

    def transmit(self, now: float) -> bytes | None:
        if self._next_status is not None and self._next_status <= now:
            return self._send_status(now)
        if self._fill_at is None or self._fill_at > now:
            return None
        self._fill_at = None
        frame = self._send_block(self._push.pop(), now) if self._push else self._fill(now)
        self._schedule(now)
        return frame

    def _gen(self, i: int) -> int:
        return max(g for g, first in enumerate(self._firsts) if first <= i)

    def _blocks(self, g: int) -> set[int]:
        return set(range(self._firsts[g], self._firsts[g] + self._sizes[g]))

    def _need(self, g: int, now: float) -> int:
        mine = self._have.keys() & self._blocks(g)
        return max([0] + [len(mine - s) for s in self._fresh(now)])

    def _fill(self, now: float) -> bytes | None:
        need, _, g = max(
            (self._need(g, now), self.rng.random(), g) for g in range(len(self._sizes))
        )
        if need == 0:
            return None
        mine = self._have.keys() & self._blocks(g)
        lacking = Counter(i for s in self._fresh(now) for i in mine - s)
        most = max(lacking.values())
        return self._send_block(self.rng.choice([i for i, c in lacking.items() if c == most]), now)

    def _progress(self, now: float) -> None:
        if len(self._have) == self.nblocks:
            self.done_at = now
            self._arm_status(now + self.rng.uniform(0, self.params.backoff * self.params.window))
        else:
            self._arm_status(now + jittered(self.params.quiet, self.rng))

    def _fresh(self, now: float) -> list[set[int]]:
        ttl = self.params.neighbour_ttl
        return [s for c, s in self._theirs.items() if now - self._heard[c] <= ttl]

    def _overheard(self, src: str, i: int, now: float) -> None:
        for call, s in self._theirs.items():
            if call != src and now - self._heard[call] <= self.params.neighbour_ttl:
                s.add(i)

    def _schedule(self, now: float) -> None:
        if self._fill_at is not None:
            return
        if self._push:
            self._fill_at = now
            return
        need = max(self._need(g, now) for g in range(len(self._sizes)))
        if need:
            p = self.params
            self._fill_at = now + p.backoff * self.rng.uniform(0, p.window) / (1 + need)

    def _send_block(self, i: int, now: float) -> bytes:
        for s in self._fresh(now):
            s.add(i)
        g = self._gen(i)
        bitmap = _bits(self._have, self._firsts[g], self._sizes[g])
        head = bytes([self.DATA]) + _HEADER[1:] + bytes([g]) + i.to_bytes(2, "big")
        return head + bitmap + self._have[i]

    def _arm_status(self, at: float) -> None:
        self._next_status = at
        self._status_wait = self.params.quiet
        self._status_left = self.params.status_repeats

    def _prompt(self, now: float, soon: bool) -> None:
        if len(self._have) == self.nblocks:
            return
        self._status_left = self.params.status_repeats
        at = now + jittered(self._status_wait, self.rng)
        if soon and now - self._last_status >= self.params.quiet / 2:
            at = now + self.rng.uniform(0, self.params.backoff * self.params.window)
        self._next_status = at if self._next_status is None else min(self._next_status, at)

    def _send_status(self, now: float) -> bytes:
        self._last_status = now
        self._status_left -= 1
        self._status_wait = min(self._status_wait * 2, self.params.quiet * 8)
        behind = any(s - self._have.keys() for s in self._theirs.values())
        incomplete = len(self._have) < self.nblocks
        keep = self._status_left > 0 or (incomplete and behind)
        self._next_status = now + jittered(self._status_wait, self.rng) if keep else None
        bitmap = b"".join(_bits(self._have, f, k) for f, k in zip(self._firsts, self._sizes))
        return bytes([self.STATUS]) + _HEADER[1:] + bitmap


def _addr(call: str) -> bytes:
    return call.encode().ljust(9)


class RoutedNode:
    """Point-to-point forwarding: one copy per destination along shortest paths, stop-and-wait
    ARQ on every hop. Routes come from the simulator, so this baseline never pays for discovery."""

    DATA, ACK = 1, 2
    RETRIES = 30

    def __init__(
        self, call: str, nblocks: int, next_hop: dict[str, str], timeout: float, rng: random.Random
    ) -> None:
        self.call = call
        self.nblocks = nblocks
        self.next_hop = next_hop
        self.timeout = timeout
        self.rng = rng
        self.done_at: float | None = None
        self._got: set[int] = set()
        self._seen: set[tuple[str, int]] = set()
        self._queue: deque[tuple[str, int, bytes]] = deque()
        self._acks: deque[bytes] = deque()
        self._retry_at: float | None = None
        self._tries = 0

    def originate(self, blocks: list[bytes], dests: list[str], now: float) -> None:
        self._queue.extend((d, i, b) for d in dests for i, b in enumerate(blocks))
        self.done_at = now

    def receive(self, frame: bytes, src: str, now: float) -> None:
        to = frame[1:10].decode().strip()
        if to != self.call:
            return
        dest, i = frame[10:19].decode().strip(), int.from_bytes(frame[19:21], "big")
        if frame[0] == self.ACK:
            if self._queue and self._retry_at is not None and self._queue[0][:2] == (dest, i):
                self._queue.popleft()
                self._retry_at = None
                self._tries = 0
            return
        self._acks.append(bytes([self.ACK]) + _addr(src) + frame[10:21])
        if dest == self.call:
            self._got.add(i)
            if len(self._got) == self.nblocks and self.done_at is None:
                self.done_at = now
        elif (dest, i) not in self._seen:
            self._seen.add((dest, i))
            self._queue.append((dest, i, frame[21:]))

    def due(self) -> float | None:
        if self._acks:
            return 0.0
        if self._queue:
            return self._retry_at if self._retry_at is not None else 0.0
        return None

    def transmit(self, now: float) -> bytes | None:
        if self._acks:
            return self._acks.popleft()
        if not self._queue or (self._retry_at is not None and self._retry_at > now):
            return None
        if self._tries >= self.RETRIES:
            self._queue.popleft()
            self._tries = 0
            self._retry_at = None
            return None
        dest, i, block = self._queue[0]
        self._tries += 1
        self._retry_at = now + self.timeout * self.rng.uniform(1, 1.5)
        hop = _addr(self.next_hop[dest])
        return bytes([self.DATA]) + hop + _addr(dest) + i.to_bytes(2, "big") + block
