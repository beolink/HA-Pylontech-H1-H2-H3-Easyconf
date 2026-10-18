"""The texts: generated, complete, and the same shape in English and Swedish."""

import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "pylontech_easyconf"


def load(name):
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def keys(data, prefix=""):
    out = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        out.add(path)
        if isinstance(value, dict):
            out |= keys(value, path)
    return out


def test_the_files_are_what_the_generator_writes():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_strings.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_english_and_swedish_have_the_same_keys():
    assert keys(load("translations/en.json")) == keys(load("translations/sv.json"))
    assert load("strings.json") == load("translations/en.json")


def test_placeholders_match_between_the_languages():
    en, sv = load("translations/en.json"), load("translations/sv.json")

    def walk(a, b, path=""):
        if isinstance(a, dict):
            for key in a:
                walk(a[key], b[key], f"{path}.{key}")
        else:
            found = set(re.findall(r"{(\w+)}", a)), set(re.findall(r"{(\w+)}", b))
            assert found[0] == found[1], path

    walk(en, sv)


def test_every_translation_key_in_the_code_has_a_name():
    entity = load("strings.json")["entity"]
    code = (PACKAGE / "sensor.py").read_text()
    used = set(re.findall(r'translation_key="(\w+)"', code)) | {"cell_voltage", "cell_temperature"}
    assert used <= set(entity["sensor"]), used - set(entity["sensor"])
    binary_code = (PACKAGE / "binary_sensor.py").read_text()
    binary = set(re.findall(r'translation_key = "(\w+)"', binary_code))
    assert binary <= set(entity["binary_sensor"])
    assert "module" in load("strings.json")["device"]


def test_every_step_of_the_flows_has_its_texts():
    code = (PACKAGE / "config_flow.py").read_text()
    shown = set(re.findall(r'step_id="(\w+)"', code))
    config = load("strings.json")["config"]["step"]
    assert shown - {"init"} <= set(config), shown - set(config)
    assert set(load("strings.json")["options"]["step"]) == {"init"}
    for reason in re.findall(r'errors\["base"\] = "(\w+)"', code):
        assert reason in load("strings.json")["config"]["error"], reason
    for reason in re.findall(r'reason="(\w+)"', code):
        assert reason in load("strings.json")["config"]["abort"], reason
    probe = (PACKAGE / "reader.py").read_text()
    for reason in set(re.findall(r'"(cannot_connect|no_battery|not_pylontech)"', probe)):
        assert reason in load("strings.json")["config"]["error"], reason


def test_no_dashes_in_the_texts():
    # The house style of these integrations: no en or em dash in a sentence.
    for name in ("translations/en.json", "translations/sv.json"):
        text = (PACKAGE / name).read_text(encoding="utf-8")
        assert chr(0x2013) not in text and chr(0x2014) not in text, name
