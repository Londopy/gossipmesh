"""Network-coded gossip for packet radio."""

from importlib.metadata import version

from ._coding import Generation, seed_coefficients

__version__ = version("gossipmesh")

__all__ = [
    "Generation",
    "seed_coefficients",
]
