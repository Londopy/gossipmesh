# Changelog

All notable changes to gossipmesh are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The section for a version is
what appears on its GitHub release page. Validated in CI by
[patchnotes](https://github.com/Londopy/patchnotes).

## [Unreleased]

### Added

- `uncoded` simulator strategy: the same protocol with coding switched off, using
  per-generation bitmaps where the coded station uses ranks, so the simulator can measure
  what coding itself saves.
- `docs/part97.md`: the US amateur rules that apply to unattended gossipmesh relaying,
  checked against the current eCFR text.
- `gossipmesh node --log` records every frame sent and heard, and `gossipmesh decode` turns
  such a log back into messages.
- `gossipmesh node --blocklist` stops relaying listed message ids without a restart.
- `gossipmesh node --relay-trusted-only` relays only messages signed by a trusted key.

### Changed

- The default back-off is 4 packet airtimes instead of 0.4. Over the simulator's sweep it
  cut coded airtime by about 40% without slowing delivery on the default map.

### Fixed

- Stations that heard the same frames sent their status requests at the same instant, and
  on a Direwolf bench they collided every time, so a message could stall. Status timers now
  carry random jitter.
- The originator's opening burst waited a random back-off before every frame, which doubled
  delivery time on small networks for no benefit.
- The simulator sensed a transmission the instant it began and always rolled `persist`.
  It now gives carrier detect a tenth of a second to notice a frame and sends at once on a
  clear channel, like Direwolf. The old model is what hid the status collisions.

## [0.1.0] - 2026-11-19

### Added

- Protocol version 1: random linear network coding over GF(256) in generations of up to 32
  blocks, with seeded packets from complete stations and vector packets from partial relays.
- Station logic driven by neighbour rank announcements, with no routes or acknowledgements.
- Simulator comparing coded gossip with plain flooding and routed forwarding, with CSMA,
  collisions and hidden stations.
- `gossipmesh node` for KISS TNCs over TCP or serial.
- Optional Ed25519 message signatures.

[Unreleased]: https://github.com/Londopy/gossipmesh/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Londopy/gossipmesh/releases/tag/v0.1.0
