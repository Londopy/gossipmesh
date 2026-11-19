"""Network-coded gossip for packet radio.

::

    from gossipmesh import Station

    a = Station("N0CALL-1")
    msg_id = a.originate(b"net tonight at 8", now=0.0)
    frame = a.transmit(now=a.due())    # AX.25 info field to hand to the TNC
    b = Station("N0CALL-2")
    b.receive(frame, "N0CALL-1", now=1.0)
"""

from importlib.metadata import version

from ._coding import Generation, seed_coefficients
from ._message import BadPacket, Envelope, check_call
from ._station import Delivery, Params, Station
from ._wire import Coded, Header, Status, decode, encode

__version__ = version("gossipmesh")

__all__ = [
    "BadPacket",
    "Coded",
    "Delivery",
    "Envelope",
    "Generation",
    "Header",
    "Params",
    "Station",
    "Status",
    "check_call",
    "decode",
    "encode",
    "seed_coefficients",
]
