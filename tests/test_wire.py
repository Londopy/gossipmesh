import pytest
from hypothesis import given
from hypothesis import strategies as st

from gossipmesh import BadPacket, Coded, Envelope, Header, Status, decode, encode
from gossipmesh._message import join, layout, sign, split, verify

H = Header(bytes(range(8)), 1_900_000_000, 5000, 128)


def test_layout_caps_generations_at_32_blocks() -> None:
    assert layout(10_000, 128) == [27, 26, 26]
    assert layout(1, 128) == [1]
    assert all(k <= 32 for k in layout(65_535, 16))


def test_split_join_round_trip() -> None:
    data = bytes(range(256)) * 20 + b"tail"
    assert join(split(data, 128), len(data)) == data


@pytest.mark.parametrize(
    "pkt",
    [
        Coded(H, 1, 3, bytes(128), seed=0xFFFFFFFF),
        Coded(H, 0, 20, bytes(range(128)), vector=bytes(range(20))),
        Status(H, bytes([20, 0])),
    ],
)
def test_packets_round_trip(pkt: Coded | Status) -> None:
    assert decode(encode(pkt)) == pkt


def test_rejects_rank_beyond_generation() -> None:
    frame = bytearray(encode(Coded(H, 0, 3, bytes(128), seed=1)))
    frame[18] = 21
    with pytest.raises(BadPacket):
        decode(bytes(frame))


@given(st.binary(max_size=400))
def test_garbage_only_raises_bad_packet(data: bytes) -> None:
    try:
        decode(data)
    except BadPacket:
        pass


@given(st.binary(max_size=200))
def test_envelope_garbage_only_raises_bad_packet(data: bytes) -> None:
    try:
        Envelope.unpack(data)
    except BadPacket:
        pass


def test_signature_checks_body() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    env = sign(Envelope("N0CALL-3", 1_900_000_000, b"hello"), key)
    back = Envelope.unpack(env.pack())
    assert back == env and verify(back, pub)
    forged = Envelope.unpack(env.pack().replace(b"hello", b"jello"))
    assert not verify(forged, pub)


def test_envelope_rejects_non_canonical_callsign() -> None:
    packed = Envelope("N0CALL", 1_900_000_000, b"x").pack()
    with pytest.raises(BadPacket):
        Envelope.unpack(packed.replace(b"N0CALL", b"n0call"))
