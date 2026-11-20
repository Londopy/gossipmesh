import random

from gossipmesh import Coded, Header, Params, Station, Status, encode
from gossipmesh._message import message_id

P = Params(backoff=0.5, quiet=20.0)


def chain(*calls: str) -> list[Station]:
    return [Station(c, P, random.Random(i)) for i, c in enumerate(calls)]


def run(
    stations: list[Station], links: dict[str, list[str]], loss: float, until: float = 5000
) -> float:
    """Take turns on one shared channel: whoever is due first sends, everyone in range may hear."""
    rng = random.Random(7)
    by_call = {s.call: s for s in stations}
    t = 0.0
    while t < until:
        due = [(d, s) for s in stations if (d := s.due()) is not None]
        if not due:
            return t
        d, s = min(due, key=lambda x: x[0])
        t = max(t, d)
        frame = s.transmit(t)
        if frame is None:
            continue
        for call in links[s.call]:
            if rng.random() >= loss:
                by_call[call].receive(frame, s.call, t)
        t += 1.5
    raise AssertionError("the network never went quiet")


LINE = {"N0AAA": ["N0BBB"], "N0BBB": ["N0AAA", "N0CCC"], "N0CCC": ["N0BBB"]}


def test_message_crosses_lossy_chain_and_network_goes_quiet() -> None:
    a, b, c = chain("N0AAA", "N0BBB", "N0CCC")
    body = random.Random(3).randbytes(6000)
    msg_id = a.originate(body, 0.0)
    run([a, b, c], LINE, loss=0.2)
    for s in (b, c):
        assert s.delivered[msg_id].envelope.body == body
        assert s.delivered[msg_id].envelope.originator == "N0AAA"


def test_signed_message_from_trusted_key() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    other = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    a, b, c = chain("N0AAA", "N0BBB", "N0CCC")
    b.keys = {"N0AAA": pub}
    c.keys = {"N0AAA": other}
    msg_id = a.originate(b"signed", 0.0, key=key)
    run([a, b, c], LINE, loss=0.0)
    assert b.delivered[msg_id].verified is True
    assert msg_id not in c.delivered, "a bad signature must not be delivered"


def test_recovers_from_a_polluting_packet() -> None:
    a, b = chain("N0AAA", "N0BBB")
    msg_id = a.originate(b"x" * 300, 0.0)
    real = next(iter(a._msgs))
    junk = Coded(real, 0, 3, bytes(range(128)), vector=bytes([1, 2, 3]))
    b.receive(encode(junk), "N0EVL", 0.0)
    run([a, b], {"N0AAA": ["N0BBB"], "N0BBB": ["N0AAA"]}, loss=0.0)
    assert b.delivered[msg_id].envelope.body == b"x" * 300


def test_ignores_expired_and_own_frames() -> None:
    a, b = chain("N0AAA", "N0BBB")
    h = Header(message_id(b"zz"), 10, 2, 128)
    old = encode(Coded(h, 0, 1, bytes(128), seed=5))
    b.receive(old, "N0AAA", 11.0)
    assert b.due() is None
    b.receive(old, "N0BBB", 1.0)
    assert b.due() is None


def test_forged_status_cannot_hijack_a_message() -> None:
    a, b = chain("N0AAA", "N0BBB")
    msg_id = a.originate(b"real" * 40, 0.0)
    real = next(iter(a._msgs))
    forged = Header(real.msg_id, real.expiry + 999, real.length, real.block_size)
    b.receive(encode(Status(forged, bytes(len(forged.gens)))), "N0EVL", 0.0)
    run([a, b], {"N0AAA": ["N0BBB"], "N0BBB": ["N0AAA"]}, loss=0.0)
    assert b.delivered[msg_id].envelope.body == b"real" * 40


def test_off_air_headers_are_capped() -> None:
    (b,) = chain("N0BBB")
    for i in range(500):
        h = Header(i.to_bytes(8, "big"), 1000, 65535, 16)
        b.receive(encode(Status(h, bytes(len(h.gens)))), "N0EVL", 0.0)
    far = Header(bytes(8), 10**9, 100, 128)
    b.receive(encode(Status(far, bytes(1))), "N0EVL", 0.0)
    assert len(b._msgs) == b.params.max_msgs
    assert far not in b._msgs, "expiry beyond max_ttl is refused"


def drain(s: Station, until: float) -> int:
    """Let s transmit into the void until it goes quiet or time runs out; count status frames."""
    sent = 0
    while (d := s.due()) is not None and d < until:
        if s.transmit(d) is not None:
            sent += 1
    return sent


def test_keeps_asking_a_neighbour_that_has_more() -> None:
    a, b = chain("N0AAA", "N0BBB")
    a.originate(bytes(3000), 0.0)
    b.receive(a.transmit(a.due() or 0.0) or b"", "N0AAA", 1.0)
    drain(b, 3000.0)
    assert b.due() is not None, "gave up although N0AAA holds what it lacks"


def test_stops_asking_when_nobody_has_more() -> None:
    (b,) = chain("N0BBB")
    h = Header(bytes(8), 80_000, 3000, 128)
    b.receive(encode(Status(h, bytes(len(h.gens)))), "N0EVL", 0.0)
    assert drain(b, 50_000.0) == P.status_repeats
    assert b.due() is None


def test_blocked_message_is_dropped_and_never_relayed() -> None:
    a, b, c = chain("N0AAA", "N0BBB", "N0CCC")
    msg_id = a.originate(b"x" * 2000, 0.0)
    b.receive(a.transmit(a.due() or 0.0) or b"", "N0AAA", 1.0)
    b.block(msg_id)
    assert b.due() is None
    run([a, b, c], LINE, loss=0.0)
    assert msg_id not in b.delivered and msg_id not in c.delivered


def signer() -> tuple[object, bytes]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = Ed25519PrivateKey.generate()
    return key, key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def test_trusted_only_relay_passes_on_trusted_messages() -> None:
    key, pub = signer()
    a, b, c = chain("N0AAA", "N0BBB", "N0CCC")
    b.keys, b.relay_trusted_only = {"N0AAA": pub}, True
    msg_id = a.originate(b"trusted" * 50, 0.0, key=key)
    run([a, b, c], LINE, loss=0.1)
    assert c.delivered[msg_id].envelope.body == b"trusted" * 50


def test_trusted_only_relay_holds_back_untrusted_messages() -> None:
    key, _ = signer()
    a, b, c = chain("N0AAA", "N0BBB", "N0CCC")
    b.relay_trusted_only = True
    msg_id = a.originate(b"unknown key" * 50, 0.0, key=key)
    run([a, b, c], LINE, loss=0.1)
    assert b.delivered[msg_id].verified is None, "the relay still reads it"
    assert msg_id not in c.delivered
