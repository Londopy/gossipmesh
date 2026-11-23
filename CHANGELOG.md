# Changelog

All notable changes to gossipmesh are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The section for a version is
what appears on its GitHub release page. Validated in CI by
[patchnotes](https://github.com/Londopy/patchnotes).

## [Unreleased]

## [0.3.0] - 2026-11-23

### Added

- `gossipmesh tui`: the node with a live view in the terminal, built on Textual (the new
  `tui` extra). It shows messages in flight with their progress, decoded messages, neighbours
  and airtime, sends typed text or files, blocks and unblocks messages, switches
  trusted-only relaying, and follows the frame log.
- `scripts/figures.py` reproduces every figure the README quotes, and `gossipmesh sim
  --backoff` sets the back-off.

### Fixed

- The README's back-off table used a different seed and run count from the headline
  comparison, and the flooding table mixed run counts; both are regenerated from the same
  seeded runs. The description of Meshtastic's flooding now matches its documentation.

## [0.2.0] - 2026-11-19

### Added

- `gossipmesh sim` reports heard/block: how many data frames a station heard before it could
  decode, per block of the message.
- README sections on how many packets decoding takes against the K + 2 design target, where
  coded gossip beats plain flooding per delivered message and where it does not, and what
  the relays' coefficient vectors cost. `docs/protocol.md` explains why a relay that has not
  decoded yet cannot send a seed, and the README says 9600 baud has only been simulated.
- `docs/rules-elsewhere.md`: how the UK, Canada, Australia, Germany and Japan treat
  unattended relays, obscured meaning and identification, with sources.
- Packet BBS forwarding (MBL/RLI, FBB, Winlink) and the PACSAT broadcast protocol in
  `docs/prior-art.md`.

## [0.1.0] - 2026-11-19

### Added

- Protocol version 1: random linear network coding over GF(256) in generations of up to 32
  blocks, with seeded packets from complete stations and vector packets from partial relays.
  The wire format is documented in `docs/protocol.md`.
- Station logic driven by neighbour rank announcements, with no routes or acknowledgements.
  Status timers carry random jitter, so receivers that heard the same frames don't ask in
  lockstep, which stalled the first bench run.
- `gossipmesh sim`: a simulator comparing coded gossip with the same protocol uncoded, plain
  flooding and routed forwarding, with Direwolf-like channel access, collisions and hidden
  stations.
- `gossipmesh node` for KISS TNCs over TCP or serial, tested on a three-station Direwolf
  bench.
- Optional Ed25519 message signatures, and `gossipmesh keygen`.
- Trickle-style beacons from stations holding a complete message, so a station that comes on
  the air late still gets it. `--beacon` sets the interval or turns them off.
- `gossipmesh node --outbox` sends every file dropped into a folder while the node runs, and
  short text messages are printed when they arrive.
- Relay controls for unattended nodes: `--log` with `gossipmesh decode`, `--blocklist` and
  `--relay-trusted-only`.
- `docs/part97.md`: the US amateur rules that apply to unattended relaying, checked against
  the current eCFR text.

[Unreleased]: https://github.com/Londopy/gossipmesh/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Londopy/gossipmesh/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Londopy/gossipmesh/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Londopy/gossipmesh/releases/tag/v0.1.0
