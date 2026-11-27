from pathlib import Path

import pytest

from panclip.config import Settings


def test_data_dir_follows_xdg_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings.load([], {"XDG_DATA_HOME": "/srv/data"})
    assert settings.data_dir == Path("/srv/data/panclip")


def test_relative_xdg_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = Settings.load([], {"XDG_DATA_HOME": "relative"})
    assert settings.data_dir == tmp_path / ".local/share/panclip"


def test_flag_overrides_environment():
    settings = Settings.load(["--data-dir", "/a"], {"PANCLIP_DATA_DIR": "/b"})
    assert settings.data_dir == Path("/a")


def test_relative_data_dir_is_refused():
    with pytest.raises(SystemExit):
        Settings.load([], {"PANCLIP_DATA_DIR": "data"})


def test_cloud_is_off_unless_asked():
    assert not Settings.load([], {}).allow_cloud
    assert Settings.load([], {"PANCLIP_ALLOW_CLOUD": "true"}).allow_cloud
    assert Settings.load(["--allow-cloud"], {}).allow_cloud
    with pytest.raises(SystemExit):
        Settings.load([], {"PANCLIP_ALLOW_CLOUD": "maybe"})


def test_limits_are_bounded():
    settings = Settings.load(
        [], {"PANCLIP_MAX_CLIPS": "5", "PANCLIP_MAX_AGE_DAYS": "1.5"}
    )
    assert (settings.max_clips, settings.max_age_days) == (5, 1.5)
    with pytest.raises(SystemExit):
        Settings.load([], {"PANCLIP_MAX_CONTENT_CHARS": "0"})
    with pytest.raises(SystemExit):
        Settings.load([], {"PANCLIP_MAX_CLIPS": "lots"})
