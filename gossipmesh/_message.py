import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

MAX_GEN = 32
SIGNATURE_LEN = 64

_CALL_RE = re.compile(r"^[A-Z0-9]{1,6}(-([0-9]|1[0-5]))?$")


class BadPacket(ValueError):
    pass


def check_call(call: str) -> str:
    """Normalise a callsign with optional SSID, or raise ValueError."""
    call = call.strip().upper()
    if not _CALL_RE.match(call) or not any(c.isdigit() for c in call.split("-")[0]):
        raise ValueError(f"{call!r} is not a callsign like N0CALL or N0CALL-7")
    return call


@dataclass(frozen=True)
class Envelope:
    """What gets coded: originator, expiry (unix seconds), body and an optional signature."""

    originator: str
    expiry: int
    body: bytes
    signature: bytes | None = None

    def _head(self, signed: bool) -> bytes:
        call = self.originator.encode("ascii")
        return bytes([int(signed), len(call)]) + call + self.expiry.to_bytes(4, "big")

    def signed_part(self) -> bytes:
        return self._head(True) + self.body

    def pack(self) -> bytes:
        return self._head(self.signature is not None) + self.body + (self.signature or b"")

    @property
    def msg_id(self) -> bytes:
        return message_id(self.pack())

    @classmethod
    def unpack(cls, data: bytes) -> "Envelope":
        if len(data) < 2 or data[0] > 1:
            raise BadPacket("envelope header is malformed")
        signed, n = data[0], data[1]
        end = 2 + n + 4
        if len(data) < end + (SIGNATURE_LEN if signed else 0):
            raise BadPacket("envelope is truncated")
        try:
            call = data[2 : 2 + n].decode("ascii")
            if check_call(call) != call:
                raise ValueError(f"{call!r} is not in canonical form")
        except (UnicodeDecodeError, ValueError) as e:
            raise BadPacket(f"envelope originator is invalid: {e}") from e
        expiry = int.from_bytes(data[2 + n : end], "big")
        if signed:
            return cls(call, expiry, data[end:-SIGNATURE_LEN], data[-SIGNATURE_LEN:])
        return cls(call, expiry, data[end:])


def message_id(packed: bytes) -> bytes:
    return hashlib.sha256(packed).digest()[:8]


def layout(length: int, block_size: int) -> list[int]:
    """Blocks per generation for a packed envelope of this length."""
    blocks = -(-length // block_size)
    gens = -(-blocks // MAX_GEN)
    base, extra = divmod(blocks, gens)
    return [base + 1 if i < extra else base for i in range(gens)]


def split(packed: bytes, block_size: int) -> list[list[bytes]]:
    padded = packed.ljust(sum(layout(len(packed), block_size)) * block_size, b"\0")
    out, pos = [], 0
    for k in layout(len(packed), block_size):
        out.append([padded[pos + i * block_size : pos + (i + 1) * block_size] for i in range(k)])
        pos += k * block_size
    return out


def join(gens: list[list[bytes]], length: int) -> bytes:
    return b"".join(b"".join(g) for g in gens)[:length]


def _crypto() -> Any:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as e:
        raise RuntimeError("signing needs the sign extra: pip install gossipmesh[sign]") from e
    return ed25519


def load_signing_key(path: Path) -> Any:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, _crypto().Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    return key


def sign(env: Envelope, key: Any) -> Envelope:
    return replace(env, signature=key.sign(env.signed_part()))


def verify(env: Envelope, public_key: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature

    if env.signature is None:
        return False
    try:
        _crypto().Ed25519PublicKey.from_public_bytes(public_key).verify(
            env.signature, env.signed_part()
        )
    except InvalidSignature:
        return False
    return True
