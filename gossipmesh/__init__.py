"""Network-coded gossip for packet radio."""

from importlib.metadata import version

from ._coding import Generation, seed_coefficients
from ._message import BadPacket, Envelope, check_call
from ._wire import Coded, Header, Status, decode, encode

__version__ = version("gossipmesh")

__all__ = [
    "BadPacket",
    "Coded",
    "Envelope",
    "Generation",
    "Header",
    "Status",
    "check_call",
    "decode",
    "encode",
    "seed_coefficients",
]
