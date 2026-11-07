"""Smoke test: proves the package installs and imports correctly."""
from filinglens import config


def test_project_root_is_correct():
    # If PROJECT_ROOT is right, pyproject.toml lives directly inside it.
    assert (config.PROJECT_ROOT / "pyproject.toml").exists()


def test_data_paths_hang_off_data_dir():
    assert config.FINANCEBENCH_DIR.is_relative_to(config.DATA_DIR)
    assert config.RUNS_DIR.is_relative_to(config.DATA_DIR)
