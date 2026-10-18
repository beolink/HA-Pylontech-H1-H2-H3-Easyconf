"""Make the integration's pure modules importable without Home Assistant.

The package's __init__ imports Home Assistant, so it is registered here as
an empty namespace pointing at the folder: the protocol, register, cloud and
report modules then import on their own, which is what lets these tests run
in seconds on a machine without Home Assistant. The Home Assistant side is
exercised by scripts/smoke_real_ha.py under a real release.
"""

from __future__ import annotations

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "pylontech_easyconf"

for name, path in (
    ("custom_components", ROOT / "custom_components"),
    ("custom_components.pylontech_easyconf", PACKAGE),
):
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

sys.path.insert(0, str(ROOT / "tests"))
