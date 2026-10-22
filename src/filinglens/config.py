"""Central place for settings.

Every other file imports settings from here instead of reading
environment variables directly, so there is one place to change them.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = two folders up from this file (src/filinglens/config.py -> filinglens/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Read key=value pairs from .env into environment variables (if .env exists).
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# The one model the whole project uses (baselines included, so comparisons are fair).
MODEL = "claude-haiku-5-5"
# How much the model "thinks" before answering. Low = cheapest and fastest.
DEFAULT_EFFORT = "low"


def require_anthropic_key() -> str:
    """Return the API key, or fail loudly with a helpful message."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-..."):
        raise RuntimeError("ANTHROPIC_API_KEY is missing. Copy .env.example to .env and add your key.")
    return ANTHROPIC_API_KEY