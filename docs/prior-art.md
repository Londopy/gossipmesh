# Prior art

This is a quick search done before building, not a literature review. Where a source was only
seen in search results or as an abstract, that is noted.

## Summary

Each mechanism gossipmesh uses has been published before. That covers random linear coding
for broadcast, relays that recode before decoding, rank feedback to stop, generations, and
seeds for source packets with full vectors for recoded ones. No amateur radio project using
network coding turned up. What is new here is putting it on AX.25 over VHF/UHF packet,
together with the engineering choices that go with that.

## Network coding in wireless meshes

- **MORE** (Chachulski, Jennings, Katti, Katabi, SIGCOMM 2007). Opportunistic unicast routing:
  the source sends random combinations of a batch, forwarders send fresh mixes without
  decoding, and every packet carries the full code vector. Forwarders get transmit credit
  from loss-rate estimates, and the destination's ACK ends the batch. gossipmesh has no single
  destination; rank announcements do the job of both credits and the ACK.
  https://courses.grainger.illinois.edu/ece598hh/sp2018/papers/more.pdf
- **COPE** (Katti et al., SIGCOMM 2006). XORs packets from different unicast flows so one
  transmission serves several next hops. It codes across flows, not within one message, so
  it is only loosely related. https://people.csail.mit.edu/rahul/papers/cope-sigcomm2006.pdf

## Broadcast and gossip with coding

- **Algebraic gossip** (Deb, Medard, Choute, IEEE Trans. Inf. Theory 2006). This is the theory
  behind mixing before decoding: coded gossip spreads k messages in about ck rounds plus a
  lower-order term. (Abstract only.)
  https://nokia.com/bell-labs/publications-and-media/publications/algebraic-gossip-a-network-coding-approach-to-optimal-multiple-rumor-mongering
- **Efficient broadcasting using network coding** (Fragouli, Widmer, Le Boudec, INFOCOM 2006
  and ToN 2008). All-to-all broadcast in ad hoc networks with distributed forwarding rules.
  This is the closest academic match. Its exact forwarding rule was not checked.
  https://infoscience.epfl.ch/record/85830/files/FWL-infocom06.pdf
- **CodeCast** (Park, Gerla, Lun, Yi, Medard, 2006). Random network coding over multicast in
  mobile ad hoc networks.
- **AdapCode** (Hou et al., INFOCOM 2008) and **Rateless Deluge** (Hagedorn, Starobinski,
  Trachtenberg, IPSN 2008). Coded firmware dissemination in sensor networks. Rateless Deluge
  receivers report how many packets they are missing rather than which ones, which is close
  to gossipmesh's rank announcements. https://sites.bu.edu/nislab/projects/rateless-deluge
- **Mixer** (Herrmann, Mager, Zimmerling, 2018). Many-to-all coded broadcast on low-power
  radios using synchronous transmissions.
  https://wwwpub.zih.tu-dresden.de/~mzimmerl/pubs/herrmann18mixer.pdf

## Coefficient overhead

- The IETF draft **draft-heide-nwcrg-rlnc-03** (2019) uses the same split gossipmesh does: a seed
  for coded symbols, explicit vectors for recoded ones.
  https://datatracker.ietf.org/doc/html/draft-heide-nwcrg-rlnc-03
- Gligoroski et al. (2015) point out that seeds do not survive recoding, and survey sparse and
  compressed vectors. https://arxiv.org/abs/1601.06449
- Tunable sparse network coding and **Fulcrum** codes (Lucani et al., 2014) cut the vector
  cost to near one bit per block. https://arxiv.org/abs/1404.6620
- **Kodo** (Steinwurf) is the main commercial RLNC library. (Seen in secondary sources only.)

## Amateur radio and LoRa

- No amateur radio network-coding project was found. Related work covers FEC on AX.25 and
  delay-tolerant networking over AX.25.
- **HQFBP** (2025) does one-to-many ham and cubesat file broadcast with optional erasure coding.
  Which code it uses was not confirmed.
- **OODC** (Tanjung et al., Sensors 2020) is LoRa with relays that recode and compressed
  coefficient headers. It covers a single relay tier and leaves hidden nodes as future work.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7602015
- No erasure or network coding was found in Meshtastic or Reticulum. Reticulum fetches
  hash-identified parts on request. That is absence of evidence, not proof.

## Packet BBS forwarding

Amateur packet radio has moved messages between many stations since the 1980s, almost all of
it over connected-mode AX.25 sessions between bulletin board systems.

- **W0RLI and WA7MBL (MBL/RLI) BBSs**, mid-1980s. BBSs opened connected-mode sessions to each
  other and pushed messages along routes set in each sysop's forward file. A bulletin carries
  a BID; a BBS that already holds it answers "NO - Already have it", and a message with a
  BID is not sent back to the station it came from. Messages without one can loop. FBB's documents still call this the "standard
  MBL/RLI protocol". Unlike gossipmesh, every transfer is a routed session with an explicit
  accept or reject.
  https://discmaster.textfiles.com/file/10596/science%20library(b).zip/science%20library(b)/PACKET/MB1107.ZIP/BID.DOC
- **Hierarchical addresses.** A message is addressed to a home BBS and region, such as
  `SP WB9LOZ @ W6PW.#NCA.CA.USA.NOAM`, and BBSs route on the address against their forward
  files (described in a 1996 introduction to packet radio). Bulletins go to a category and a distribution designator that
  differs by region. Delivery depends on every sysop keeping a routing table current;
  gossipmesh floods instead and needs no tables.
  https://www.qsl.net/l/lu7did/docs/ax25/packet/part06.html
- **F6FBB (FBB)**, from 1986 and still maintained. Batched forwarding: the sender proposes up
  to five messages (type, sender, BBS, recipient, BID or MID, size), the receiver accepts,
  rejects or defers each, and duplicates are refused at the proposal. The B flag adds
  compressed forwarding (B1F). It is a negotiated, acknowledged transfer over a connection,
  where gossipmesh sends without negotiating and receivers drop duplicates themselves.
  https://www.qsl.net/pe1nmb/bbs/fbb/docfwpro.htm and https://www.qsl.net/lu3erx/docfwcom.html
- **Winlink B2F**, 2000s to now. A later level of FBB's forwarding protocol, used by
  Winlink, where clients connect to gateways that pass mail to a central server: a
  hub-and-gateway email system, not a peer-to-peer flood. Details were not checked against
  the specification, which could not be fetched; wl2k-go implements it.
  https://github.com/la5nta/wl2k-go
- **PACSAT Broadcast Protocol** (Price and Ward, about 1990). The closest amateur radio
  prior art. A
  satellite splits a file into AX.25 UI frames, each carrying a file id, a byte offset and a
  CRC, and repeats them round robin. Any frame can be stored on its own, ground stations send
  lists of holes, and the missing pieces go back into the broadcast. There are no ACKs. It
  differs from gossipmesh in having one sender of plain blocks and in needing hole lists:
  with coding, a station only has to say how many pieces it lacks, and any station can
  supply them. https://www.ir3ip.net/iw3fqg/doc/pacsat.htm

## Patents

Random linear network coding has been the subject of patents. This search did not look into
which ones exist or whether any are still in force. Check before building anything
commercial on gossipmesh. The Apache-2.0 license grants contributors' patent rights, not
third parties'.
