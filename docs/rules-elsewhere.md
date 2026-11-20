# Rules outside the US

[part97.md](part97.md) covers the US. This is a shorter look at five other countries, for the
three things gossipmesh most depends on: running relays unattended, the ban on codes that
obscure meaning, and identification. It was put together in November 2026 from the sources
named below, with their dates. Rules change, translations lose detail, and some points could
not be confirmed; those are marked. It is not legal advice. Read your own regulator's current
text before going on the air.

Two points apply everywhere. gossipmesh sends no encryption, and a signature leaves the text
readable. But a single coded frame is not readable on its own: it takes enough frames
together, decoded with the published method, to recover a message. No regulator text found
addresses network coding directly. The arguments that it does not obscure meaning are that
the code is published, anyone can decode it with public software, and `gossipmesh node
--log` keeps a record that `gossipmesh decode` turns back into the messages.

## United Kingdom

Ofcom amateur radio licence conditions (OFW611) and guidance, both published 21 February
2024, read from the copies at https://wiki.oarc.uk/_export/xhtml/licence because ofcom.org.uk
refused automated access. Ofcom made further changes in October 2025, and it was not
confirmed whether these clauses changed.

- **Unattended operation:** condition 6(11) requires remote-control links to be adequately
  secure, transmissions to be able to stop promptly, and the licence number to be shown on
  the equipment. Condition 6(17) lets a "Data Station" be operated, but not controlled, by
  other amateurs without supervision, at up to 5 W ERP. It must be possible to close it
  down within 2 hours, and the licensee keeps evidence of the steps taken to avoid
  interference. Condition 6(18) allows up to 25 W ERP for Intermediate and Full licensees,
  with a call sign allocated through the RSGB. The guidance says most data stations no
  longer need a Notice of Variation, except above 25 W ERP.
- **What may be sent:** condition 6(20)(c) allows "Messages transmitted by a Beacon or via a
  Data Station for reception by Amateurs", and the guidance says this covers bulletin board
  and mailbox operation. That reads as covering gossipmesh's kind of traffic, though the
  conditions do not mention it by name.
- **Obscured meaning:** condition 6(19)(b) requires transmissions to be not encrypted for the
  purpose of obscuring their meaning, except for satellite command.
- **Identification:** condition 6(21) sets no interval. The station must be clearly
  identifiable at all times, sending its call sign as often as practicable. Every gossipmesh
  frame carries it.

## Canada

RBR-4 Issue 3 (July 2022), the Radiocommunication Regulations SOR/96-484 (current to
29 October 2026) and RIC-3 Issue 5 (March 2022).

- **Unattended operation:** no explicit rule on unattended or automatic data stations was
  found. RBR-4 section 11 says signals may not be automatically retransmitted below
  29.5 MHz, unless the incoming signal comes from an operator qualified to operate below
  30 MHz. Regulations section 44(b)(i) requires the Advanced qualification to install
  equipment that receives and automatically retransmits radiotelephone communications in the
  same band; whether that reaches data relays was not confirmed. RIC-3 section 4.5.2
  requires Advanced for remote control of fixed stations. Keeping gossipmesh relays above
  30 MHz avoids the first of these.
- **Obscured meaning:** Regulations section 47(b) allows only a code or cipher "that is not
  secret".
- **Identification:** RBR-4 section 9 requires the assigned call sign at the start and end of
  each exchange and at intervals of no more than 30 minutes.

## Australia

Radiocommunications (Amateur Stations) Class Licence 2023 (F2023L01648), as made on
7 December 2023, in force from 19 February 2024. Later compilations were not checked.

- **Unattended operation:** section 13(4) allows a station to run with nobody present only in
  an automatic or computer-controlled mode, with a timer that shuts it down if a fault keeps
  it transmitting unintentionally for more than 10 minutes. gossipmesh frames last about a
  second, so the timer is a property of the radio or TNC: use a radio with a transmit
  time-out. Section 13(2)(b) does not allow operating as an amateur repeater station under
  the class licence; whether a gossipmesh relay counts as one depends on a definition that
  was not checked.
- **Obscured meaning:** section 13(2)(d)(iv) bans signals encoded for the purpose of
  obscuring their meaning.
- **Identification:** section 12(1) requires the call sign at the beginning and end of each
  transmission and at least every 10 minutes. Each frame carries it in the AX.25 header; that
  this satisfies "end of each transmission" was not confirmed.

## Germany

Amateurfunkverordnung (AFuV), last amended 27 May 2024, at
https://www.gesetze-im-internet.de/afuv_2005/

- **Unattended operation:** section 13(1) requires a separate call sign allocation for every
  remotely controlled or automatic station, tied to its site, and section 13(2) requires a
  site-specific compatibility assessment first. Read plainly, each unattended gossipmesh
  relay would need its own allocation from the Bundesnetzagentur.
- **Obscured meaning:** section 16(7) requires traffic in open language. Section 16(8) says
  transmission methods must allow the content to be recovered with generally available
  technology or the corresponding knowledge and skills, and forbids traffic coded or
  encrypted to conceal its content, apart from control signals. A published code with a
  free decoder is the kind of method the first sentence describes; whether the regulator
  agrees for network coding was not checked.
- **Identification:** section 11(1) requires the call sign at the start and end of each
  contact and at least every ten minutes.

The wider CEPT framework (T/R 61-01) was not researched.

## Japan

Radio Act (電波法) and Radio Station Operation Rules (無線局運用規則), from the e-Gov law
texts.

- **Unattended operation:** no rule on unattended or automatic amateur stations was
  confirmed.
- **Obscured meaning:** Radio Act article 58 says amateur stations must not use secret codes
  (暗語).
- **Identification:** Operation Rules article 10(3) requires the station's identification
  signal on its transmissions. No amateur-specific interval was found.
- **Relaying for others:** article 259 says amateur messages must not be sent at someone
  else's request, except in emergencies. That bears directly on relaying other people's
  messages, so check it before running a relay in Japan.

## In short

Of these, the UK's data station conditions come closest to describing a gossipmesh relay.
Germany appears to ask the most of an unattended relay, with a separate allocation for each.
Australia needs a transmit time-out and leaves open whether a relay is a repeater. Canada's
restriction on automatic retransmission is below 29.5 MHz, but no rule on data relays above
it was found either way. Japan's ban on sending messages at others' request needs a closer
reading.
