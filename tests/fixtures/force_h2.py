"""A real Force H2 read through its Solarman logger, 2026-09-29.

Two FH9637M modules of 30 cells. The summary block (0x1100-0x113F) and the
cell voltages (0x1500-) are the dumps published with goodwe_manager's
Pylontech poller (https://github.com/piomar123/goodwe_manager, MIT licence,
tests/test_bms_poller.py); the Solarman app showed cell temperatures 27.2 and
25.7 degC and a state of health of 97 % at the time. The module and cell
temperature blocks are the ones that test pairs with the dump, consistent with
its summary. The identity block and the serial number are made up in the
shape the published register scans give them.
"""

SUMMARY = (
    [1027, 0, 0, 1965, 0, 0, 360, 33, 679, 2160, 0, 1850, 1740, 65535, 63686, 3]
    + [3276, 3273, 3, 24, 280, 250, 30, 22, 9825, 9824, 0, 1, 272, 257, 1, 0]
    + [97, 0, 2347, 0, 2652, 0, 4021, 0, 2652, 0, 4046, 0, 4942, 0, 4902, 0]
    + [0, 0, 0, 0, 0, 0, 2, 60, 0, 0, 0, 0, 0, 0, 0, 0]
)
CELLS = (
    [3276, 3275, 3276, 3277, 3275, 3276, 3276, 3276, 3275, 3276, 3276, 3276, 3275, 3276, 3276]
    + [3276, 3277, 3277, 3275, 3276, 3275, 3276, 3276, 3275, 3273, 3276, 3276, 3276, 3277, 3275]
    + [3276, 3275, 3277, 3276, 3275, 3276, 3277, 3274, 3275, 3274, 3275, 3275, 3275, 3276, 3277]
    + [3277, 3275, 3277, 3274, 3275, 3277, 3276, 3275, 3277, 3276, 3276, 3277, 3277, 3274, 3275]
)
MODULE_VOLTAGES = [9825, 9824]
MODULE_TEMPERATURES = [257, 272]
CELL_TEMPERATURES = [260] * 22 + [250] * 8 + [280] * 15 + [270] * 15


def text_words(text: str, words: int) -> list[int]:
    raw = text.encode("ascii").ljust(2 * words, b"\x00")[: 2 * words]
    return [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw), 2)]


SERIAL = "PPTBH0231A123456"
IDENTITY = text_words("Pylon", 5) + text_words("Force_H2", 5) + [0x0106] + [0] * 5


def bank() -> dict[int, int]:
    """Every register the fake logger answers, by address."""
    out: dict[int, int] = {}

    def put(start: int, words: list[int]) -> None:
        for offset, word in enumerate(words):
            out[start + offset] = word

    put(0x1000, IDENTITY)
    put(0x1100, SUMMARY)
    put(0x1400, SUMMARY)
    put(0x1450, text_words(SERIAL, 8))
    put(0x1460, MODULE_VOLTAGES + [0] * 14)
    put(0x14B0, MODULE_TEMPERATURES + [0] * 14)
    put(0x1500, CELLS + [0] * 196)
    put(0x1800, CELL_TEMPERATURES + [0] * 196)
    return out
