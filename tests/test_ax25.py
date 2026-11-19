from gossipmesh._ax25 import FEND, FESC, KissReader, kiss_wrap, parse_ui, ui_frame


def test_ui_frame_round_trip_keeps_ssid() -> None:
    assert parse_ui(ui_frame("N0CALL-15", b"data")) == ("N0CALL-15", b"data")
    assert parse_ui(ui_frame("K1A", b"")) == ("K1A", b"")


def test_ignores_other_traffic() -> None:
    frame = bytearray(ui_frame("N0CALL", b"x"))
    frame[0] = ord("A") << 1
    assert parse_ui(bytes(frame)) is None
    assert parse_ui(b"\x00" * 5) is None


def test_kiss_escapes_and_reassembles_split_stream() -> None:
    a = ui_frame("N0CALL-1", bytes([FEND, FESC, 1, 2]))
    b = ui_frame("N0CALL-2", b"second")
    stream = kiss_wrap(a) + kiss_wrap(b) + bytes([FEND, 0x10]) + b"other port" + bytes([FEND])
    reader = KissReader()
    got = []
    for i in range(0, len(stream), 7):
        got += reader.feed(stream[i : i + 7])
    assert got == [a, b]
