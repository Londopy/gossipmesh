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
coded     190/190    1999    2726       143.5           1193      2185        3185
uncoded   190/190    3070    4047       213.0           1773      2586        3548
flood     0/190      389     550        -               -         -           399
routed    105/190    13720   15818      1506.5          12001     20098       21599
```

## What's here

- The protocol, written up in [docs/protocol.md](docs/protocol.md) so anyone can decode it.
- A station implementation that does no I/O, so the simulator and the radio run the same
  code.
- A simulator: stations scattered on a map, with packet loss that rises toward the edge of
  range, channel access that behaves like Direwolf's, collisions and hidden stations. It compares coded gossip with
  the same protocol uncoded, plain flooding, and point-to-point forwarding.
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

The comparison that matters is with **uncoded**. That is the same protocol with coding
switched off: the same generations, timers, back-off and opening push. A data frame carries
the sender's bitmap for that block's generation where a coded packet carries its rank, and a
status carries bitmaps where Station's carries ranks. Neighbours resend the plain blocks a
bitmap shows missing. Both reached every station on every map tried. Coding saved between
a fifth and a third of the airtime, and the farthest station decoded a little sooner:

| Scenario | Coded airtime | Uncoded airtime | Coded / uncoded | Farthest decode, coded vs uncoded |
|---|---|---|---|---|
| default (1200 baud, 10% loss) | 2,726 s | 4,047 s | 67% | 2,185 s vs 2,586 s |
| `--loss 0.3` | 3,776 s | 5,138 s | 73% | 3,295 s vs 3,452 s |
| `--area 3.5`, 30 runs | 2,453 s | 3,214 s | 76% | 2,604 s vs 3,057 s |
| `--area 4.0`, 30 runs | 2,534 s | 3,079 s | 82% | 3,124 s vs 3,185 s |
| `--baud 9600 --txdelay 0.1 --block 256` | 325 s | 423 s | 77% | 375 s vs 490 s |

How big the saving is depends on the back-off, the random wait before a station answers a
neighbour's deficit. Longer waits let stations overhear each other and skip redundant
frames, which helps both strategies and helps uncoded more. Over 8 runs on the default map,
with the back-off in units of one packet's airtime:

| Back-off | Coded airtime | Uncoded airtime | Coded / uncoded | Farthest decode, coded vs uncoded |
|---|---|---|---|---|
| 0.4 | 3,613 s | 7,419 s | 49% | 2,251 s vs 2,626 s |
| 1 | 3,325 s | 5,784 s | 57% | 1,691 s vs 2,493 s |
| 2 | 2,969 s | 4,166 s | 71% | 2,067 s vs 2,122 s |
| **4 (default)** | 2,100 s | 2,876 s | 73% | 2,129 s vs 2,295 s |
| 8 | 1,726 s | 2,123 s | 81% | 2,048 s vs 2,525 s |
| 16 | 1,521 s | 1,794 s | 85% | 2,886 s vs 3,556 s |

On the sparser `--area 4.0` map the two are within 7% of each other from a back-off of 8
up, and uncoded reaches the farthest station sooner there. The default of 4 is a trade-off:
at 8 the default map uses another fifth less airtime, but on the sparse map the farthest
station then waits about a quarter longer. These are simulator results
from a guessed loss model, so treat the exact figures with suspicion; the bench test below
checks the protocol itself, not the comparison.

Plain flooding (each station repeats each block once, with no repair) used a fifth of
coded's airtime but reached no station at all: with 79 blocks, losing any one of them means
failure. Routed forwarding (one copy per destination along shortest paths, stop-and-wait ARQ
per hop, routes given for free) used almost six times the airtime and reached 105 of 190
stations before the 6-hour limit. After the last station decodes, completed stations repeat
a short status a few times, which is the gap between "farthest" and "quiet at".

At 9600 baud with 256-byte blocks, routed forwarding also reached every station, using
almost nine times coded's airtime and taking 15 times as long. Flooding reached none.

The simulator's channel access was corrected after the bench test below showed how
Direwolf behaves.

## Bench test with a real modem

Run two or three Direwolf instances, each with its own `MYCALL`, `KISSPORT` and `AGWPORT`.
Connect their audio through loopback, for example with a virtual audio cable, or wire the
radios into dummy loads. A Direwolf config for one station on a shared virtual cable looks
like this (`ADEVICE` takes the input and output device numbers Direwolf lists at startup):

```
ADEVICE 1 4
ACHANNELS 1
CHANNEL 0
MYCALL N0CALL-1
MODEM 1200
KISSPORT 8001
AGWPORT 8000
```

Then start one node per Direwolf:

```bash
gossipmesh node --call N0CALL-1 --kiss 127.0.0.1:8001 --out received --send notes.txt
```

```bash
gossipmesh node --call N0CALL-2 --kiss 127.0.0.1:8011 --out received2
```

Each node prints a line when it decodes a message and saves the body under `--out`, named by
message id. A hardware TNC in KISS mode works with `--serial COM3 --serial-baud 9600`. For
9600 baud radios, pass `--baud 9600` so the node paces itself to the channel.

### What the bench showed

Three Direwolf 1.8.1 instances at 1200 baud shared one virtual audio cable on Windows, so
every station heard every other one. No radios were involved.

- The first 10 KB run never finished. A quarter of the frames were lost on the cable, so the
  receivers had to ask for more. Both had heard the same frames at the same moments, so
  their status timers expired together. Direwolf sends at once when the channel is clear,
  so the two requests collided on every round, and the sender never heard one. Status
  timers now carry random jitter, and the simulator now models this channel access.
  Without the fix it reproduces the stall.
- With the fix, a 10 KB message reached both receivers in 204 seconds, at about 8% loss.
  The sender sent 91 frames, an opening burst of 85 and 6 repairs after each receiver asked
  twice.
- On the final code (back-off of 4 packet times, opening burst sent back to back) a 2 KB
  message reached both receivers in 29 seconds and a 10 KB message in 129 seconds. Loss was
  low on that run, 2 of 85 frames, so the opening burst's 2 spare frames per generation
  covered it and nobody had to ask. 85 frames take about 125 seconds of airtime at
  1200 baud, so delivery came as soon as the burst ended.

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

Read [docs/part97.md](docs/part97.md), a section-by-section reading of the US rules checked
against eCFR on 2026-11-19. In short: unattended relaying of data is allowed on 6 m and up,
and only in a few narrow segments on HF. A gossipmesh network counts as a message forwarding
system, so originators answer for content, and signatures are how relays authenticate them.
The protocol is public and unencrypted, and every frame carries the sending station's call
sign. It is not legal advice, and other countries' rules differ.

## License

Apache-2.0. See [LICENSE](LICENSE). It includes a patent grant, which matters for a protocol
other people may implement.
