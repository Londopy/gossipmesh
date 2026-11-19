import struct
from dataclasses import dataclass
from functools import cached_property

from ._message import BadPacket, layout

VERSION = 1
SEEDED, VECTOR, STATUS = 1, 2, 3
MIN_BLOCK, MAX_BLOCK = 16, 1024

_HEAD = struct.Struct(">B8sIHH")
_CODED = struct.Struct(">BB")
_SEED = struct.Struct(">I")


@dataclass(frozen=True)
class Header:
    msg_id: bytes
    expiry: int
    length: int
    block_size: int

    @cached_property
    def gens(self) -> list[int]:
        return layout(self.length, self.block_size)


@dataclass(frozen=True)
class Coded:
    header: Header
    gen: int
    rank: int
    payload: bytes
    seed: int | None = None
    vector: bytes | None = None


@dataclass(frozen=True)
class Status:
    header: Header
    ranks: bytes


def _head(kind: int, h: Header) -> bytes:
    return _HEAD.pack(VERSION << 4 | kind, h.msg_id, h.expiry, h.length, h.block_size)


def encode(pkt: Coded | Status) -> bytes:
    if isinstance(pkt, Status):
        return _head(STATUS, pkt.header) + pkt.ranks
    if pkt.seed is not None:
        coeffs = _SEED.pack(pkt.seed)
        kind = SEEDED
    elif pkt.vector is not None:
        coeffs = pkt.vector
        kind = VECTOR
    else:
        raise ValueError("coded packet needs a seed or a vector")
    return _head(kind, pkt.header) + _CODED.pack(pkt.gen, pkt.rank) + coeffs + pkt.payload


def decode(data: bytes) -> Coded | Status:
    if len(data) < _HEAD.size:
        raise BadPacket("packet is shorter than the header")
    tag, msg_id, expiry, length, block_size = _HEAD.unpack_from(data)
    if tag >> 4 != VERSION:
        raise BadPacket(f"unknown protocol version {tag >> 4}")
    if length == 0 or not MIN_BLOCK <= block_size <= MAX_BLOCK:
        raise BadPacket("header has an impossible length or block size")
    h = Header(msg_id, expiry, length, block_size)
    kind, rest = tag & 0xF, data[_HEAD.size :]
    if kind == STATUS:
        if len(rest) != len(h.gens) or any(r > k for r, k in zip(rest, h.gens)):
            raise BadPacket("status ranks do not match the message layout")
        return Status(h, rest)
    if kind not in (SEEDED, VECTOR) or len(rest) < _CODED.size:
        raise BadPacket(f"unknown packet type {kind}")
    gen, rank = _CODED.unpack_from(rest)
    if gen >= len(h.gens) or rank > h.gens[gen]:
        raise BadPacket("generation or rank is out of range")
    rest = rest[_CODED.size :]
    clen = _SEED.size if kind == SEEDED else h.gens[gen]
    if len(rest) != clen + block_size:
        raise BadPacket("coded packet has the wrong length")
    if kind == SEEDED:
        return Coded(h, gen, rank, rest[clen:], seed=_SEED.unpack_from(rest)[0])
    return Coded(h, gen, rank, rest[clen:], vector=rest[:clen])
