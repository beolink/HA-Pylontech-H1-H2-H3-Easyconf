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


def test_the_shared_statistics_client_is_unchanged():
    # stats.py is copied verbatim between the beolink integrations.
    text = (PACKAGE / "stats.py").read_text()
    assert 'ENDPOINT = "https://stats.rnet.se/api/v1/report"' in text
    assert "SCHEMA_VERSION = 3" in text
