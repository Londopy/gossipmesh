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
- **PACSAT** broadcast files as AX.25 UI frames with hole-fill requests and no coding. (Seen in
  search summaries only.)
- **HQFBP** (2025) does one-to-many ham and cubesat file broadcast with optional erasure coding.
  Which code it uses was not confirmed.
- **OODC** (Tanjung et al., Sensors 2020) is LoRa with relays that recode and compressed
  coefficient headers. It covers a single relay tier and leaves hidden nodes as future work.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7602015
- No erasure or network coding was found in Meshtastic or Reticulum. Reticulum fetches
  hash-identified parts on request. That is absence of evidence, not proof.

## Patents

Random linear network coding has been the subject of patents. This search did not look into
which ones exist or whether any are still in force. Check before building anything
commercial on gossipmesh. The Apache-2.0 license grants contributors' patent rights, not
third parties'.
