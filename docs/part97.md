# Part 97 and gossipmesh

This is a reading of the US amateur rules (47 CFR Part 97) as they apply to running
gossipmesh stations unattended. It was checked against eCFR on 2026-11-19 (eCFR text current
to 2026-11-18). It is one operator's reading, not legal advice. Other countries' rules
differ.

## Short version

- **2 m, 70 cm and every band from 6 m up:** unattended gossipmesh stations may relay data.
  The 1200 and 9600 baud packet modes fit the emission limits there.
- **HF:** unattended relaying is allowed only in a few narrow segments. HF data is also
  limited to the specified codes, and gossipmesh's coded payload depends on the
  "publicly documented technique" clause. Stay on VHF/UHF until that has been looked at more
  closely.
- A gossipmesh network is very likely a **message forwarding system**. That puts the
  originator on the hook for content and asks something of the first station to relay it,
  which is where signatures help.
- The code is fine on the obscured-meaning rule as long as the spec stays public and
  nobody uses it to hide content. A Regional Director can ask for a record of what was sent.

## Automatic control

97.109(d): "When a station is being automatically controlled, the control operator need not
be at the control point. Only stations specifically designated elsewhere in this part may be
automatically controlled. Automatic control must cease upon notification by a Regional
Director that the station is transmitting improperly or causing harmful interference to
other stations."

97.221(b): "A station may be automatically controlled while transmitting a RTTY or data
emission on the 6 m or shorter wavelength bands, and on the 28.120-28.189 MHz, 24.925-24.930
MHz, 21.090-21.100 MHz, 18.105-18.110 MHz, 14.0950-14.0995 MHz, 14.1005-14.112 MHz,
10.140-10.150 MHz, 7.100-7.105 MHz, or 3.585-3.600 MHz segments."

97.221(c) allows automatic control elsewhere on HF only when "the station is responding to
interrogation by a station under local or remote control" and the transmission is no wider
than 500 Hz.

For gossipmesh:

- On 6 m and up, an unattended node is allowed. 97.221(a) excludes repeaters, beacons and
  auxiliary stations from this section. A gossipmesh node is none of those: it does not
  retransmit simultaneously on another channel.
- On HF, unattended relaying belongs in the 97.221(b) segments. The 97.221(c) exception
  does not fit. A relay sends when its neighbours' statuses ask, and those neighbours are
  usually automatic stations too, not stations under local or remote control.
- The operator has to be able to stop a node promptly if a Regional Director says so.
  Stopping `gossipmesh node` does that.

## Third-party traffic

97.3(a)(47): "Third party communications. A message from the control operator (first party)
of an amateur station to another amateur station control operator (second party) on behalf of
another person (third party)."

97.115(c): "No station may transmit third party communications while being automatically
controlled except a station transmitting a RTTY or data emission."

A message a licensed operator writes and sends for themselves is not third-party traffic.
If someone does relay third-party traffic, an automatic data station may carry it, within
97.115(a)'s limits on foreign stations. Keeping originators licensed avoids the question.

## Message forwarding systems

97.3(a)(32): "Message forwarding system. A group of amateur stations participating in a
voluntary, cooperative, interactive arrangement where communications are sent from the
control operator of an originating station to the control operator of one or more
destination stations by one or more forwarding stations."

97.219:

- (b) "the control operator of the station originating a message is primarily accountable
  for any violation of the rules in this part contained in the message."
- (c) Forwarding stations "that retransmit inadvertently communications that violate the
  rules in this part are not accountable for the violative communications. They are,
  however, responsible for discontinuing such communications once they become aware of their
  presence."
- (d) "the control operator of the first forwarding station must: (1) Authenticate the
  identity of the station from which it accepts communications on behalf of the system; or
  (2) Accept accountability for any violation of the rules in this part contained in
  messages it retransmits to the system."

gossipmesh fits that definition. The originator's control operator answers for what a
message says. In a gossip network, every station that hears the originator directly is a
"first forwarding station". An Ed25519 signature checked against a trusted key is a strong
way to authenticate the originator. Without one, those first relays accept accountability
for the content.

What gossipmesh gives an operator for this:

- `gossipmesh node --blocklist FILE` stops relaying any message whose id is in FILE, one id
  per line. The node re-reads the file whenever it changes, so adding a line takes effect
  within a second, without a restart (97.219(c)).
- `gossipmesh node --relay-trusted-only --trust FILE` relays a message only after decoding
  it and checking it is signed by a key in FILE. That relies on 97.219(d)(1) instead of
  (d)(2). It costs the main trick: such a node cannot pass on pieces before it has decoded
  the whole message, so delivery past it is slower.

## Obscured meaning and digital codes

97.113(a)(4) prohibits "messages encoded for the purpose of obscuring their meaning".

97.309(a)(4): "An amateur station transmitting a RTTY or data emission using a digital code
specified in this paragraph may use any technique whose technical characteristics have been
documented publicly, such as CLOVER, G-TOR, or PacTOR, for the purpose of facilitating
communications."

97.309(b) allows unspecified digital codes where 97.305(c) and 97.307(f) permit them:
"RTTY and data emissions using unspecified digital codes must not be transmitted for the
purpose of obscuring the meaning of any communication." A Regional Director may require a
station to "Maintain a record, convertible to the original information, of all digital
communications transmitted."

For gossipmesh: the network coding exists to get messages through loss, not to hide
them. The spec and code are public, and anyone with the reference decoder can read every
message. Signatures leave the content readable. Keep it that way: no encryption, and no
compressed or binary payloads without a public description of how to read them.

`gossipmesh node --log FILE` appends every frame the node sends and hears to FILE.
`gossipmesh decode FILE` turns that log back into the messages it holds. That is the record
97.309(b)(3) describes, if a Regional Director ever asks for one. The heard frames matter:
a relay's own transmissions are mixes of what it heard, and only together do they decode.

## Emission limits

From the 97.305(c) table and 97.307(f), for the bands that matter here:

| Band | Standards | What they allow |
|---|---|---|
| 6 m (50.1-54.0 MHz), 2 m (144.1-148.0 MHz) | 97.307(f)(5) | Specified or unspecified codes, symbol rate up to 19.6 kilobauds, bandwidth 20 kHz |
| 1.25 m (222-225 MHz), 70 cm (whole band) | 97.307(f)(6) | Specified or unspecified codes, symbol rate up to 56 kilobauds, bandwidth 100 kHz |
| HF data segments (for example 80 m, 40 m) | 97.307(f)(3) | "Only a RTTY or data emission using a specified digital code listed in § 97.309(a) may be transmitted. The authorized bandwidth is 2.8 kHz" |

1200 baud AFSK and 9600 baud packet fit easily on 2 m and 70 cm. On HF there is no longer a
symbol-rate limit (except on 2200 m and 630 m), but only the specified codes (Baudot, AMTOR
and ASCII, 97.309(a)(1)-(3)) are allowed. A gossipmesh packet is mixed binary, not ASCII. It
would have to count as a publicly documented technique applied to an ASCII message under
97.309(a)(4), the way PacTOR's compression does. That is a reasonable argument for plain
text bodies, but it is an argument, not a settled answer.

## Identification

97.119(a): each station must transmit its call sign "at the end of each communication, and at
least every 10 minutes during a communication". 97.119(b)(3) allows identifying "By a RTTY
emission using a specified digital code when all or part of the communications are
transmitted by a RTTY or data emission".

Every gossipmesh frame carries the sending station's call sign in the AX.25 source address,
so a station identifies on every transmission. That is the usual way packet stations
identify.

## One-way transmissions

97.113(b) prohibits one-way communications "except as specifically provided in these
rules". 97.111(b) lists the allowed kinds, including "Transmissions necessary to
disseminate information bulletins". 97.3(a)(26) defines an information bulletin as "A
message directed only to amateur operators consisting solely of subject matter of direct
interest to the amateur service."

gossipmesh is interactive: stations exchange status reports and answer each other's
requests, so it is not a one-way broadcast. Messages meant for "everyone" should still stick
to amateur-interest content, which keeps them within the information-bulletin allowance
anyway.

## Business and pay

97.113(a)(2)-(3) prohibit communications for hire and communications in which the licensee or
control operator has a pecuniary interest, including on behalf of an employer, with narrow
exceptions for emergency drills. This applies to message content like any other mode.
