import random

from hypothesis import given, settings
from hypothesis import strategies as st

from gossipmesh import Generation, seed_coefficients
from gossipmesh._gf import Bytes

MSG = bytes(8)


def blocks_for(k: int, size: int, seed: int) -> list[bytes]:
    rng = random.Random(seed)
    return [rng.randbytes(size) for _ in range(k)]


def seeded(src: Generation, g: int, seed: int) -> tuple[Bytes, Bytes]:
    coeffs = seed_coefficients(MSG, g, seed, src.k)
    return coeffs, src.encode(coeffs)


@settings(max_examples=50, deadline=None)
@given(k=st.integers(1, 32), size=st.sampled_from([16, 64, 128]), seed=st.integers(0, 2**32 - 1))
def test_decodes_from_seeded_packets(k: int, size: int, seed: int) -> None:
    blocks = blocks_for(k, size, seed)
    src = Generation.from_blocks(blocks)
    dst = Generation(k, size)
    sent = 0
    while not dst.complete:
        dst.add(*seeded(src, 0, (seed + sent) % 2**32))
        sent += 1
        assert dst.rank <= k
    assert dst.blocks() == blocks
    assert sent <= k + 5


def test_relay_recodes_before_decoding() -> None:
    rng = random.Random(1)
    blocks = blocks_for(32, 128, 2)
    src = Generation.from_blocks(blocks)
    relay = Generation(32, 128)
    for i in range(20):
        relay.add(*seeded(src, 0, i))
    assert relay.rank == 20 and not relay.complete

    dst = Generation(32, 128)
    for _ in range(25):
        dst.add(*relay.recode(rng))
    assert dst.rank == 20, "a relay can only pass on what it holds"
    i = 100
    while not dst.complete:
        dst.add(*seeded(src, 0, i))
        i += 1
    assert i - 100 <= 15
    assert dst.blocks() == blocks


def test_duplicate_is_not_innovative() -> None:
    src = Generation.from_blocks(blocks_for(8, 32, 3))
    dst = Generation(8, 32)
    packet = seeded(src, 0, 7)
    assert dst.add(*packet)
    assert not dst.add(*packet)
    assert dst.rank == 1


def test_seed_coefficients_match_the_spec() -> None:
    # other implementations must regenerate exactly these bytes; see docs/protocol.md
    assert (
        seed_coefficients(bytes(range(8)), 1, 0xDEADBEEF, 8).tobytes().hex() == "f3102bf268f48bee"
    )


def test_decoding_takes_about_k_packets() -> None:
    # the design target is about k + 2; over GF(256) a random mix is almost never redundant
    rng = random.Random(5)
    extra = []
    for _ in range(300):
        src = Generation.from_blocks(blocks_for(32, 16, rng.getrandbits(32)))
        dst = Generation(32, 16)
        sent = 0
        while not dst.complete and sent < 40:
            dst.add(*seeded(src, 0, rng.getrandbits(32)))
            sent += 1
        assert dst.complete and dst.blocks() == src.blocks()
        extra.append(sent - 32)
    assert min(extra) >= 0, "nothing decodes from fewer than k packets"
    assert max(extra) <= 2
    assert sum(extra) / len(extra) < 0.05
