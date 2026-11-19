# gossipmesh protocol, version 1

This is the full description of what gossipmesh puts on the air. It is published so anyone can
decode every transmission with their own software, as FCC Part 97.309(a)(4) requires of a
digital code. Nothing in the protocol is encrypted. The coding is linear algebra over a public
field, and the reference decoder is in this repository.

All integers are big-endian. "Bytes" means octets.

## Framing

Every transmission is one AX.25 UI frame:

- destination address `GMESH` (SSID 0)
- source address: the transmitting station's own callsign and SSID
- no digipeater path (stations relay the content themselves)
- control `0x03`, PID `0xF0`
- information field: one gossipmesh packet (below)

The source address identifies the station on every frame, which covers 97.119 as long as the
station transmits under its own call. With a KISS TNC, frames go on TNC port 0.

## Messages

A message is an *envelope*:

| Field | Size | Meaning |
|---|---|---|
| flags | 1 | `0x01` if a signature follows the body, else `0x00` |
| call length | 1 | n |
| originator | n | the originator's callsign (see below) |
| expiry | 4 | unix time (seconds) after which stations drop the message |
| body | rest | the message itself, any bytes |
| signature | 64 | Ed25519 signature, only when flags is `0x01` |

The originator is written exactly as it would appear in an AX.25 address: 1 to 6 upper case
letters and digits including at least one digit, then optionally `-` and an SSID from 0 to
15 with no leading zero. Receivers reject envelopes with any other spelling. That way one
signed message cannot be re-spelled into several valid message ids.

The signature covers every byte before it, with flags already set to `0x01`.

The **message id** is the first 8 bytes of SHA-256 over the whole packed envelope. A station
that decodes a message checks this hash before accepting it.

The packed envelope (length L, at most 65535) is cut into blocks of B bytes, the last one
padded with zeros. With N = ceil(L / B) blocks, the blocks are grouped into
G = ceil(N / 32) *generations*. The first N mod G generations hold floor(N / G) + 1 blocks and
the rest hold floor(N / G). Blocks go into generations in order. A generation of k blocks is
decoded on its own, and each needs k independent packets.

For example, L = 10,000 and B = 128 give 79 blocks in generations of 27, 26 and 26.

## Coding

Arithmetic is in GF(256) with the reducing polynomial x^8 + x^4 + x^3 + x^2 + 1 (`0x11D`).
Addition is XOR.

A coded packet for generation g carries a coefficient vector c of length k and a payload
P = sum(c[i] * block[i]), computed bytewise over the generation's k blocks.

The vector is sent in one of two ways:

- **Seeded.** A station that holds the whole generation picks a random 32-bit seed s. Then
  c = the first k bytes of SHA-256(`"gossipmesh"` || message id || g as 1 byte || s as 4 bytes).
- **Vector.** A station that holds only part of the generation sends a random combination of
  the packets it has. It cannot express that combination as a seed, so it sends the k-byte
  vector itself.

A test vector: message id `0001020304050607`, generation 1, seed `0xDEADBEEF` gives
coefficients starting `f3102bf268f48bee`. If your implementation gets the same bytes, its
seeds will interoperate.

## Packets

Every packet starts with the same 17-byte header:

| Field | Size | Meaning |
|---|---|---|
| type | 1 | high nibble is the version (1), low nibble the packet type |
| message id | 8 | |
| expiry | 4 | the envelope's expiry, so stations can drop stale traffic before decoding |
| length | 2 | L, the packed envelope length |
| block size | 2 | B, 16 to 1024 |

From L and B a receiver knows the generation layout.

**Seeded coded packet** (type `0x11`):

| Field | Size |
|---|---|
| header | 17 |
| generation | 1 |
| sender rank | 1 |
| seed | 4 |
| payload | B |

**Vector coded packet** (type `0x12`): the same, with the k-byte coefficient vector in place of
the seed.

**Status** (type `0x13`): the header followed by one byte per generation, giving the sender's
rank (how many independent packets it holds) for each.

Sender rank in a coded packet is the sender's rank for that generation. It lets neighbours
know how far along the sender is without a separate status.

Receivers drop packets that are malformed, expired, carry an unknown version, or expire more
than a day ahead. They track a message by its whole header, not the id alone. A forged
header with a real id then becomes a separate message that never decodes, and it cannot
block the real one.

## Station behaviour

This part is not needed to decode transmissions. It describes how the reference station
decides when to transmit. Other implementations can do better and still interoperate.

- A station stores what it hears from every sender and tracks each neighbour's rank per
  generation from their coded packets and status packets.
- A station with rank r transmits for a generation while some recently heard neighbour reports
  rank below r. Whatever that neighbour has, a station with a higher rank holds something it
  lacks, so a fresh random mix is very likely to help. After sending, the station assumes
  every such neighbour gained one.
- When a station hears a coded packet from a sender whose rank is above a neighbour's
  estimate, it assumes the neighbour heard it too and raises the estimate.
- The originator starts with k + 2 packets of credit per generation. It sends them back to
  back, with no neighbours known. Relays get no blind credit by default; if given some, they
  spend it with the usual back-off.
- Before a coded transmission that fills a neighbour's deficit, a station waits a random time
  drawn from `[0, backoff * window]` and divided by (1 + the largest deficit it can fill), so
  stations that can help most go first. The TNC's own carrier sense then applies.
- An incomplete station that has heard nothing new for `quiet` seconds sends a status. It
  doubles that wait each time (capped at 8 times `quiet`). It gives up after 6 unanswered
  statuses, unless some neighbour it has heard is ahead of it. In that case it keeps asking
  at the capped rate until the message expires, because a lossy link to the one station
  that can help is exactly when asking matters.
- The quiet timer and the repeat gaps are multiplied by a random factor between 0.75 and
  1.25. Completion statuses and quick replies to a status are already spread over
  `[0, backoff * window]`. Stations that heard the same frames would otherwise time out at
  the same instant. On the bench, Direwolf sent
  both receivers' statuses together every round, and they collided every time.
- A station that hears a status showing a neighbour ahead of it replies with its own status
  soon, at most once per `quiet / 2`.
- A station that completes a message sends a status, then repeats it 5 more times on the same
  doubling schedule. Neighbours stop sending to it, and a neighbour that missed everything
  learns the message exists.
- The reference defaults, in units of one coded packet's airtime, are a back-off of 4, a
  window of 10 and a quiet time of 20.
- A station tracks at most 64 messages at once. It reserves decoding memory for a generation
  only when a coded packet for it arrives.
- If a decoded message fails its hash check, a bad packet was mixed in. The station discards
  what it holds for that message and starts over. If the hash matches but the envelope is
  malformed, the originator sent a bad message, and the station ignores that id until it
  expires.
- If the station has the originator's public key and the signature does not verify, it
  discards the message and ignores further packets for that id until it expires.

## Known limits

- A station that comes on the air after its neighbours have stopped repeating their
  completion status never hears about the message. Periodic beacons would fix this at an
  airtime cost.
- A forged status that claims to be ahead keeps the stations that hear it asking every
  8 * `quiet` seconds until that message expires (a day at most). Each listener sends one
  short frame per forged message per interval, for up to 64 messages.
- Anyone can transmit coded packets for a message id. A bad packet costs a restart of that
  message at the stations that took it in. A determined jammer can keep this up; signatures
  only stop a forged message from being *accepted*.
- Partial relays pay up to 32 bytes per packet for the coefficient vector. GF(2) vectors (4
  bytes for 32 blocks) would cut that, at the cost of about 1.6 extra packets per generation.

## Part 97 notes

These are the author's reading, not checked against the current rule text. Read the eCFR
version of Part 97 before going on the air.

- 97.113(a)(4): no encryption. Signatures are allowed because the content stays readable.
- 97.309(a)(4): this document and the source code are the public description of the code.
- 97.119: every frame carries the transmitting station's callsign.
- 97.221: a station that relays without an operator present is under automatic control. That
  is limited to certain HF segments; check the band you use. VHF and UHF are simpler.
- Keep originators licensed, so relayed messages raise no third-party traffic questions.
