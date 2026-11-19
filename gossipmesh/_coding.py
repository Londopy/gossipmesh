import hashlib
import random

import numpy as np

from ._gf import INV, MUL, Bytes, combine, scale


def seed_coefficients(msg_id: bytes, gen: int, seed: int, k: int) -> Bytes:
    """Coefficients a seeded packet uses: the first k bytes of SHA-256 over id, gen and seed."""
    digest = hashlib.sha256(b"gossipmesh" + msg_id + bytes([gen]) + seed.to_bytes(4, "big"))
    out: Bytes = np.frombuffer(digest.digest()[:k], dtype=np.uint8).copy()
    return out


class Generation:
    """Coded rows for one generation, kept in reduced row echelon form."""

    def __init__(self, k: int, size: int) -> None:
        if not 1 <= k <= 32:
            raise ValueError(f"generation size {k} is outside 1..32")
        self.k = k
        self.size = size
        # allocated on first use, so headers heard off the air cost almost nothing
        self._rows = np.zeros((0, 0), dtype=np.uint8)
        self._have = np.zeros(k, dtype=bool)

    @classmethod
    def from_blocks(cls, blocks: list[bytes]) -> "Generation":
        gen = cls(len(blocks), len(blocks[0]))
        gen._rows = np.zeros((gen.k, gen.k + gen.size), dtype=np.uint8)
        gen._rows[:, : gen.k] = np.eye(gen.k, dtype=np.uint8)
        gen._rows[:, gen.k :] = np.frombuffer(b"".join(blocks), dtype=np.uint8).reshape(gen.k, -1)
        gen._have[:] = True
        return gen

    @property
    def rank(self) -> int:
        return int(self._have.sum())

    @property
    def complete(self) -> bool:
        return bool(self._have.all())

    def add(self, coeffs: Bytes, payload: Bytes) -> bool:
        """Add a coded packet. Returns True if it raised the rank."""
        if len(coeffs) != self.k or len(payload) != self.size:
            raise ValueError("coded packet does not match the generation shape")
        if self._rows.size == 0:
            self._rows = np.zeros((self.k, self.k + self.size), dtype=np.uint8)
        row = np.concatenate([coeffs, payload]).astype(np.uint8)
        held = np.nonzero(self._have)[0]
        row ^= combine(row[held], self._rows[held])
        nonzero = np.nonzero(row[: self.k])[0]
        if nonzero.size == 0:
            return False
        pivot = int(nonzero[0])
        row = scale(int(INV[row[pivot]]), row)
        self._rows[held] ^= MUL[self._rows[held, pivot][:, None], row[None, :]]
        self._rows[pivot] = row
        self._have[pivot] = True
        return True

    def blocks(self) -> list[bytes]:
        if not self.complete:
            raise ValueError("generation is not decoded yet")
        return [bytes(r) for r in self._rows[:, self.k :]]

    def encode(self, coeffs: Bytes) -> Bytes:
        """Payload for the given coefficients. Only valid once complete."""
        if not self.complete:
            raise ValueError("generation is not decoded yet")
        return combine(coeffs, self._rows[:, self.k :])

    def recode(self, rng: random.Random) -> tuple[Bytes, Bytes]:
        """A fresh random mix of the held rows, as (coefficient vector, payload)."""
        held = self._rows[self._have]
        if len(held) == 0:
            raise ValueError("nothing to recode")
        mix = np.array([rng.randrange(1, 256) for _ in held], dtype=np.uint8)
        row = combine(mix, held)
        return row[: self.k], row[self.k :]
