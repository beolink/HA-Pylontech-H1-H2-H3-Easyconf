"""What the anonymous daily report may contain (stats_extra.py): the family,
the transport, the size and the firmware, never a reading or a serial."""

from custom_components.pylontech_easyconf.stats_extra import FailureCounter, build_extra


def _extra(**kw):
    args = {"model": "Force H2", "transport": "solarman_v5", "modules": 2,
            "cells_per_module": 30, "cell_data": True, "firmware": "1.6", "failures": 0}
    args.update(kw)
    return build_extra(**args)


def test_only_the_agreed_keys():
    extra = _extra()
    assert set(extra) == {"models", "features", "metrics", "errors", "firmware"}
    assert extra["models"] == ["force_h2"]
    assert extra["metrics"] == {"modules": 2, "cells_per_module": 30}
    assert extra["features"] == {"solarman_v5": True, "modbus_tcp": False,
                                 "rtu_over_tcp": False, "cloud": False, "cell_data": True}


def test_an_unknown_family_is_sent_as_force():
    assert _extra(model="Something else")["models"] == ["force"]
    assert _extra(model=None)["models"] == ["force"]


def test_nothing_unknown_is_sent_as_zero():
    extra = _extra(modules=None, cells_per_module=None, firmware=None)
    assert extra["metrics"] == {}
    assert "firmware" not in extra


def test_features_are_booleans_only():
    assert all(isinstance(v, bool) for v in _extra(transport="cloud")["features"].values())


def test_failures_since_the_last_report():
    counter = FailureCounter()
    assert counter.delta(0) == 0
    assert counter.delta(4) == 4
    assert counter.delta(4) == 0
    assert counter.delta(1) == 1  # a reload started the count again
