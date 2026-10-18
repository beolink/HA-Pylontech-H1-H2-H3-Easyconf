"""A Force H3 string of three FH10050 modules, 32 cells each: 96 cells.

Made up, not read: no published dump of a Force H3 exists yet. It follows
the H2 dump's layout, which ha-solarman's profile reads the same way on the
H3, with the H3's figures: 102.4 V and 50 Ah per module, 32 cells per module.
The coldest cell is module 2's cell 5, the fullest module 3's cell 32, and one
temperature is below zero to exercise the signed words.
"""

from .force_h2 import text_words

MODULES = 3
CELLS_PER_MODULE = 32


def _cells() -> list[int]:
    cells = [3300] * (MODULES * CELLS_PER_MODULE)
    cells[95] = 3342  # module 3, cell 32: the highest
    cells[40] = 3281  # module 2, cell 9: the lowest
    return cells


CELLS = _cells()
CELL_TEMPERATURES = [150] * 96
CELL_TEMPERATURES[36] = 65536 - 15  # module 2, cell 5: -1.5 degC
CELL_TEMPERATURES[70] = 190  # module 3, cell 7: the warmest
MODULE_VOLTAGES = [
    round(sum(CELLS[m * 32:(m + 1) * 32]) / 10) for m in range(MODULES)
]
MODULE_TEMPERATURES = [152, 65536 - 10, 175]
VOLTAGE = round(sum(CELLS) / 100)  # 0.1 V

SUMMARY = [0] * 64
SUMMARY[0x00] = 0x0801  # charging
SUMMARY[0x03] = VOLTAGE
SUMMARY[0x04], SUMMARY[0x05] = 0, 1250  # 12.5 A
SUMMARY[0x06] = 245
SUMMARY[0x07] = 64
SUMMARY[0x08] = 211
SUMMARY[0x09] = 3456
SUMMARY[0x0A], SUMMARY[0x0B] = 0, 5000
SUMMARY[0x0C] = 2784
SUMMARY[0x0D], SUMMARY[0x0E] = 0xFFFF, 0x10000 - 5000
SUMMARY[0x10], SUMMARY[0x11], SUMMARY[0x12], SUMMARY[0x13] = 3342, 3281, 95, 40
SUMMARY[0x14], SUMMARY[0x15], SUMMARY[0x16], SUMMARY[0x17] = 190, 65536 - 15, 70, 36
SUMMARY[0x18], SUMMARY[0x19], SUMMARY[0x1A], SUMMARY[0x1B] = (
    max(MODULE_VOLTAGES), min(MODULE_VOLTAGES),
    MODULE_VOLTAGES.index(max(MODULE_VOLTAGES)), MODULE_VOLTAGES.index(min(MODULE_VOLTAGES)),
)
SUMMARY[0x1C], SUMMARY[0x1D], SUMMARY[0x1E], SUMMARY[0x1F] = 175, 65536 - 10, 2, 1
SUMMARY[0x20] = 99
SUMMARY[0x21], SUMMARY[0x22] = 0, 9830
SUMMARY[0x23], SUMMARY[0x24] = 0, 3100
SUMMARY[0x25], SUMMARY[0x26] = 0, 1200
SUMMARY[0x2B], SUMMARY[0x2C] = 0, 3260
SUMMARY[0x2D], SUMMARY[0x2E] = 0, 3105
SUMMARY[0x36] = MODULES
SUMMARY[0x37] = MODULES * CELLS_PER_MODULE

SERIAL = "PPTFH3C0B9876543"
IDENTITY = text_words("Pylon", 5) + text_words("Force_H3", 5) + [0x0201] + [0] * 5


def bank() -> dict[int, int]:
    out: dict[int, int] = {}

    def put(start: int, words: list[int]) -> None:
        for offset, word in enumerate(words):
            out[start + offset] = word

    put(0x1000, IDENTITY)
    # Only the 0x1400 mirror, as ha-solarman reads it: the reader must find it.
    put(0x1400, SUMMARY)
    put(0x1450, text_words(SERIAL, 8))
    put(0x1460, MODULE_VOLTAGES + [0] * 13)
    put(0x14B0, MODULE_TEMPERATURES + [0] * 13)
    put(0x1500, CELLS)
    put(0x1800, CELL_TEMPERATURES)
    return out
