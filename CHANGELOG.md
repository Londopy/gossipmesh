# Changelog

All notable changes to gossipmesh are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The section for a version is
what appears on its GitHub release page. Validated in CI by
[patchnotes](https://github.com/Londopy/patchnotes).

## [Unreleased]

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
