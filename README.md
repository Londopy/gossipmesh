# gossipmesh

[![CI](https://github.com/Londopy/gossipmesh/actions/workflows/ci.yml/badge.svg)](https://github.com/Londopy/gossipmesh/actions/workflows/ci.yml)
[![changelog](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Londopy/gossipmesh/gh-pages/changelog-badge.json)](CHANGELOG.md)
[![License](https://img.shields.io/github/license/Londopy/gossipmesh)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-3776AB)](pyproject.toml)

**Get a message to every station in a packet radio network with no routes, connections or
per-packet ACKs.**

A message is cut into blocks, and every packet on the air is a random mix of those blocks
(random linear network coding over GF(256)). Stations keep whatever they hear, from anyone,
and send fresh mixes of it on to their neighbours before they can decode anything. A station
decodes once it holds enough independent mixes, whichever stations they came from. Stations
announce how much they hold, so the network goes quiet once everyone nearby has the message.

```console
$ gossipmesh sim --runs 10
strategy  delivered  frames  airtime s  air/delivery s  median s  farthest s  quiet at s
coded     190/190    2861    3953       208.1           1338      2325        3263
flood     0/190      476     673        -               -         -           289
routed    90/190     13069   15023      1669.2          11605     20375       21599
```

## What's here

- The protocol, written up in [docs/protocol.md](docs/protocol.md) so anyone can decode it.
- A station implementation that does no I/O, so the simulator and the radio run the same
  code.
- A simulator: stations scattered on a map, with packet loss that rises toward the edge of
  range, p-persistent CSMA, collisions and hidden stations. It compares coded gossip with
  plain flooding and with point-to-point forwarding.
- `gossipmesh node`, which runs a station against a KISS TNC over TCP (Direwolf, UZ7HO
  soundmodem) or a serial port.
- Optional Ed25519 signatures. They prove who sent a message, and the content stays
  readable.
- A short [prior-art survey](docs/prior-art.md).

## Install

gossipmesh is not on PyPI yet. From a checkout:

```bash
pip install -e ".[all]"
```

The `all` extra pulls in `cryptography` for signatures and `pyserial` for serial TNCs. Without
it you get the simulator and KISS over TCP, with only numpy as a dependency.

## Simulate

```bash
gossipmesh sim --runs 10
```

The default map is 20 stations on a square 3 radio ranges wide, sending a 10 KB message at
1200 baud with 128-byte blocks and 10% loss inside range. Every strategy runs on the same
maps. `gossipmesh sim --help` lists the knobs (`--stations`, `--area`, `--loss`, `--baud`,
`--size`, `--block`, `--strategy`).

The columns:

- **delivered:** stations that ended up with the whole message, summed over runs.
- **airtime s:** total channel time used per run, all stations added up.
- **air/delivery s:** airtime divided by stations reached.
- **median s** and **farthest s:** time until a station decodes, and until the last one does.
- **quiet at s:** when the last frame went out.

On the default map, coded gossip reached every station in every run. Plain flooding (each
station repeats each block once, with no repair) used about a sixth of the airtime but
reached no station at all: with 79 blocks, losing any one of them means failure. Routed
forwarding (one copy per destination along shortest paths, stop-and-wait ARQ per hop, routes
given for free) used almost four times the airtime and reached 90 of 190 stations before the
6-hour limit. After the last station decodes, completed stations repeat a short status a few
times, which is the gap between "farthest" and "quiet at".

At 9600 baud with 256-byte blocks
(`gossipmesh sim --runs 10 --baud 9600 --txdelay 0.1 --block 256`), coded gossip reached all
190 stations, with the farthest decoding after about 290 seconds. Routed forwarding also got
there, using 9 times the airtime and taking 23 times as long. Flooding reached none.

On sparser maps, where more links sit near the edge of range, coded gossip still reached all
570 stations over 30 runs each at `--area 3.5` and `--area 4.0`.

None of this has been on the air yet. The simulator's loss model, its timings and the
station's back-off rules are all guesses that a bench test should check.

## Bench test with a real modem

Run two or three Direwolf instances, each with its own `MYCALL`, `KISSPORT` and `AGWPORT`.
Connect their audio through loopback, for example with a virtual audio cable, or wire the
radios into dummy loads. Then start one node per Direwolf:

```bash
gossipmesh node --call N0CALL-1 --kiss 127.0.0.1:8001 --out received --send notes.txt
```

```bash
gossipmesh node --call N0CALL-2 --kiss 127.0.0.1:8011 --out received2
```

Each node prints a line when it decodes a message and saves the body under `--out`, named by
message id. A hardware TNC in KISS mode works with `--serial COM3 --serial-baud 9600`. For
9600 baud radios, pass `--baud 9600` so the node paces itself to the channel.

## Signing

```bash
gossipmesh keygen n0call.pem --call N0CALL-1
```

This writes the private key and prints a `N0CALL-1 <public key>` line. Collect those lines
from the stations you trust into a file. Then sign with `--key n0call.pem` and check with
`--trust trusted.txt`. Nodes drop a message whose signature fails for a key they hold. A
message signed by a key they don't hold is delivered and marked untrusted.

Keep the `.pem` file to yourself. Anyone with it can sign as you.

## Before going on the air

Read [the Part 97 notes](docs/protocol.md#part-97-notes). In short: the protocol is public
and unencrypted, and every frame carries the sending station's callsign. A node relaying
with nobody at the radio is under automatic control, which Part 97.221 limits on HF. VHF and
UHF are simpler.

## License

Apache-2.0. See [LICENSE](LICENSE). It includes a patent grant, which matters for a protocol
other people may implement.
