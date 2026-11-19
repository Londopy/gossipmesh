import numpy as np
import numpy.typing as npt

Bytes = npt.NDArray[np.uint8]


def _tables() -> tuple[Bytes, Bytes]:
    exp = np.zeros(510, dtype=np.uint8)
    log = np.zeros(256, dtype=np.int64)
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    exp[255:510] = exp[0:255]
    nz = np.arange(1, 256)
    mul = np.zeros((256, 256), dtype=np.uint8)
    mul[1:, 1:] = exp[log[nz][:, None] + log[nz][None, :]]
    inv = np.zeros(256, dtype=np.uint8)
    inv[1:] = exp[255 - log[nz]]
    return mul, inv


MUL, INV = _tables()


def scale(c: int, row: Bytes) -> Bytes:
    out: Bytes = MUL[c][row]
    return out


def combine(coeffs: Bytes, rows: Bytes) -> Bytes:
    """Sum of coeffs[i] * rows[i] over GF(256)."""
    if len(coeffs) == 0:
        return np.zeros(rows.shape[1], dtype=np.uint8)
    products: Bytes = MUL[coeffs[:, None], rows]
    out = np.empty(rows.shape[1], dtype=np.uint8)
    np.bitwise_xor.reduce(products, axis=0, out=out)
    return out
