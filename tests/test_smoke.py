"""Smoke test: proves the package installs and imports correctly."""
from filinglens import config


def test_project_root_is_correct():
    # If PROJECT_ROOT is right, pyproject.toml lives directly inside it.
    assert (config.PROJECT_ROOT / "pyproject.toml").exists()


def test_data_dir_is_inside_project():
    assert config.DATA_DIR.parent == config.PROJECT_ROOT
