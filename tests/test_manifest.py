"""The manifest, HACS's file and the changelog agree."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "pylontech_easyconf"


def manifest():
    return json.loads((PACKAGE / "manifest.json").read_text())


def test_domain_is_the_folder():
    assert manifest()["domain"] == PACKAGE.name


def test_the_version_is_the_changelog_s_newest():
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", (ROOT / "CHANGELOG.md").read_text(), re.M)
    assert newest and newest.group(1) == manifest()["version"]


def test_no_library_to_install():
    # The protocols are the integration's own (modbus.py, solarman_v5.py), so
    # Home Assistant installs nothing and no library version can break it.
    assert manifest()["requirements"] == []


def test_hacs_floor():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["homeassistant"] >= "2026.5.0"
    assert hacs["name"] == manifest()["name"]


def _png_size(path):
    import struct

    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", data[16:24])


def test_the_brand_images_home_assistant_reads():
    # Home Assistant 2026.3 and later read them from the integration's own
    # brand/ folder, and HACS's default list checks for them there.
    brand = PACKAGE / "brand"
    assert _png_size(brand / "icon.png") == (256, 256)
    assert _png_size(brand / "icon@2x.png") == (512, 512)
    for stem in ("logo", "dark_logo"):
        w, h = _png_size(brand / f"{stem}.png")
        w2, h2 = _png_size(brand / f"{stem}@2x.png")
        assert h == 128 and (w2, h2) == (2 * w, 2 * h), stem
    allowed = {f"{dark}{kind}{size}.png" for dark in ("", "dark_") for kind in ("icon", "logo")
               for size in ("", "@2x")}
    assert {p.name for p in brand.iterdir()} <= allowed


def test_the_shared_statistics_client_is_unchanged():
    # stats.py is copied verbatim between the beolink integrations.
    text = (PACKAGE / "stats.py").read_text()
    assert 'ENDPOINT = "https://stats.rnet.se/api/v1/report"' in text
    assert "SCHEMA_VERSION = 3" in text
