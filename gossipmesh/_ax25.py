DEST = "GMESH"
FEND, FESC, TFEND, TFESC = 0xC0, 0xDB, 0xDC, 0xDD
_UI, _NO_L3 = 0x03, 0xF0


def _addr(call: str, ssid_bits: int) -> bytes:
    base, _, ssid = call.partition("-")
    return bytes(ord(c) << 1 for c in base.ljust(6)) + bytes([ssid_bits | int(ssid or 0) << 1])


def _call(raw: bytes) -> str:
    base = bytes(b >> 1 for b in raw[:6]).decode("ascii").rstrip()
    ssid = raw[6] >> 1 & 0x0F
    return f"{base}-{ssid}" if ssid else base


def ui_frame(src: str, info: bytes) -> bytes:
    """AX.25 UI frame from src to the GMESH group address, without the FCS (the TNC adds it)."""
    return _addr(DEST, 0xE0) + _addr(src, 0x61) + bytes([_UI, _NO_L3]) + info


def parse_ui(frame: bytes) -> tuple[str, bytes] | None:
    """(source callsign, info) for a GMESH UI frame, or None for anything else."""
    pos = 0
    calls = []
    while True:
        if len(frame) < pos + 7:
            return None
        try:
            calls.append(_call(frame[pos : pos + 7]))
        except UnicodeDecodeError:
            return None
        pos += 7
        if frame[pos - 1] & 1:
            break
    if len(calls) < 2 or calls[0] != DEST or frame[pos : pos + 2] != bytes([_UI, _NO_L3]):
        return None
    return calls[1], frame[pos + 2 :]


def kiss_wrap(frame: bytes, port: int = 0) -> bytes:
    body = frame.replace(bytes([FESC]), bytes([FESC, TFESC])).replace(
        bytes([FEND]), bytes([FESC, TFEND])
    )
    return bytes([FEND, port << 4]) + body + bytes([FEND])


class KissReader:
    """Splits a KISS byte stream into data frames for one TNC port."""

    def __init__(self, port: int = 0) -> None:
        self.port = port
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        frames = []
        while (end := self._buf.find(FEND, 1 if self._buf[:1] == bytes([FEND]) else 0)) != -1:
            chunk = bytes(self._buf[:end]).lstrip(bytes([FEND]))
            del self._buf[:end]
            if chunk and chunk[0] == self.port << 4:
                frames.append(_unescape(chunk[1:]))
        return frames


def _unescape(data: bytes) -> bytes:
    out = bytearray()
    it = iter(data)
    for b in it:
        if b == FESC:
            b = next(it, FESC)
            out.append(FEND if b == TFEND else FESC if b == TFESC else b)
        else:
            out.append(b)
    return bytes(out)
