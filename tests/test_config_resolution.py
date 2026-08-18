"""Config resolution: CLI flag > SKILL_MONITOR_CONFIG env > packaged defaults.

No container and no volume: a tmp_path standing in for /config is the whole
fixture. The last test in this file is the one that matters most -- it is the
path every other test in the repo, and CI, actually runs on.
"""

import json

import pytest

import skill_monitor


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    """No ambient config leaks in, and no CLI choice leaks out to the next test."""
    monkeypatch.delenv(skill_monitor.CONFIG_ENV, raising=False)
    skill_monitor.set_config_dir(None)
    yield
    skill_monitor.set_config_dir(None)


def _config_root(base, name, *, specs=None, adapters=None):
    """Build a /config-shaped tree: <base>/<name>/{specs,adapters}.

    A subdirectory given as None is not created at all -- that is the partially
    populated volume, which is a real deployment state, not a malformed fixture.
    """
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    for sub, files in (("specs", specs), ("adapters", adapters)):
        if files is None:
            continue
        (root / sub).mkdir()
        for fname in files:
            (root / sub / fname).write_text(json.dumps({"marker": f"{name}/{sub}"}))
    return root


def test_cli_flag_beats_env_beats_packaged_default(tmp_path, monkeypatch):
    from_cli = _config_root(tmp_path, "cli", specs=["formulas_g1.json"])
    from_env = _config_root(tmp_path, "env", specs=["formulas_g1.json"])

    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(from_env))
    assert skill_monitor.config_dir() == from_env
    assert skill_monitor.config_source() == "env"
    assert skill_monitor.spec_path("g1").parent == from_env / "specs"

    skill_monitor.set_config_dir(from_cli)
    assert skill_monitor.config_dir() == from_cli
    assert skill_monitor.config_source() == "cli"
    assert skill_monitor.spec_path("g1").parent == from_cli / "specs"

    skill_monitor.set_config_dir(None)
    monkeypatch.delenv(skill_monitor.CONFIG_ENV)
    assert skill_monitor.config_dir() is None
    assert skill_monitor.config_source() == "packaged"
    assert skill_monitor.spec_path("g1").parent == skill_monitor.PACKAGED_SPECS_DIR


def test_missing_config_dir_falls_back_to_packaged_and_reports_it(tmp_path, monkeypatch):
    """A container started without its volume boots -- loudly, not silently."""
    absent = tmp_path / "not-mounted"
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(absent))

    assert skill_monitor.config_dir() is None
    assert skill_monitor.config_source() == "packaged"
    assert skill_monitor.specs_dir() == skill_monitor.PACKAGED_SPECS_DIR
    assert skill_monitor.adapters_dir() == skill_monitor.PACKAGED_ADAPTERS_DIR
    assert skill_monitor.spec_path("g1").exists()

    report = skill_monitor.config_report()
    assert str(absent) in report and "packaged" in report


def test_spec_path_and_adapters_dir_honour_the_same_override(tmp_path, monkeypatch):
    root = _config_root(
        tmp_path, "config", specs=["formulas_g1.json"], adapters=["real_g1.json"])
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(root))

    assert skill_monitor.specs_dir() == root / "specs"
    assert skill_monitor.adapters_dir() == root / "adapters"
    assert skill_monitor.spec_path("g1") == root / "specs" / "formulas_g1.json"
    assert json.loads(skill_monitor.spec_path("g1").read_text())["marker"] == "config/specs"


def test_volume_spec_wins_over_the_baked_one_of_the_same_name(tmp_path, monkeypatch):
    """The point of the volume: the robot's spec, not the image's."""
    root = _config_root(tmp_path, "config", specs=["formulas_g1.json"])
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(root))

    resolved = skill_monitor.spec_path("g1")
    assert resolved != skill_monitor.PACKAGED_SPECS_DIR / "formulas_g1.json"
    assert json.loads(resolved.read_text())["marker"] == "config/specs"


def test_a_packaged_only_spec_still_resolves_through_a_mounted_config(tmp_path, monkeypatch):
    """The mounted dir is searched first, not exclusively -- a /config carrying one
    skill must not hide the images's other specs."""
    root = _config_root(tmp_path, "config", specs=["formulas_other.json"])
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(root))

    assert skill_monitor.spec_path("other") == root / "specs" / "formulas_other.json"
    assert skill_monitor.spec_path("g1") == skill_monitor.PACKAGED_SPECS_DIR / "formulas_g1.json"


def test_partial_config_root_falls_back_per_directory(tmp_path, monkeypatch):
    """A /config with specs but no adapters must not take the descriptors away."""
    root = _config_root(tmp_path, "config", specs=["formulas_g1.json"])
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(root))

    assert skill_monitor.specs_dir() == root / "specs"
    assert skill_monitor.adapters_dir() == skill_monitor.PACKAGED_ADAPTERS_DIR


def test_unknown_spec_names_every_directory_searched(tmp_path, monkeypatch):
    root = _config_root(tmp_path, "config", specs=["formulas_g1.json"])
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(root))

    with pytest.raises(FileNotFoundError) as exc:
        skill_monitor.spec_path("no_such_skill")
    message = str(exc.value)
    assert str(root / "specs") in message
    assert str(skill_monitor.PACKAGED_SPECS_DIR) in message


def test_packaged_defaults_still_resolve_with_no_env_set():
    """The CI path. Nothing mounted, no flag, no env -- everything still resolves."""
    assert skill_monitor.config_dir() is None
    assert skill_monitor.config_source() == "packaged"
    assert skill_monitor.specs_dir() == skill_monitor.PACKAGED_SPECS_DIR
    assert skill_monitor.adapters_dir() == skill_monitor.PACKAGED_ADAPTERS_DIR
    assert (skill_monitor.adapters_dir() / "nav_schema.json").exists()
    assert skill_monitor.spec_path("g1").exists()
    assert skill_monitor.spec_path("formulas_g1.json") == skill_monitor.spec_path("g1")


def test_add_config_argument_gives_every_entry_point_the_same_flag():
    import argparse

    parser = argparse.ArgumentParser()
    skill_monitor.add_config_argument(parser)
    assert parser.parse_args([]).config is None
    assert parser.parse_args(["--config", "/config"]).config == "/config"
