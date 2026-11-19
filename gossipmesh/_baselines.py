"""Uncoded strategies the simulator compares against. Not part of the protocol."""

import heapq
import random
from collections import deque

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
