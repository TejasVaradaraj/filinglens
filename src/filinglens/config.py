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

# Large data (PDFs, run outputs) can live outside the repo. The repo sits on an
# iCloud-synced Desktop, and iCloud can offload files to the cloud, which makes
# reads hang. Set FILINGLENS_DATA_DIR in .env to keep data somewhere safe.
DATA_DIR = Path(os.getenv("FILINGLENS_DATA_DIR", PROJECT_ROOT / "data")).expanduser()
FINANCEBENCH_DIR = DATA_DIR / "raw" / "financebench"
RUNS_DIR = DATA_DIR / "runs"
CACHE_DIR = DATA_DIR / "cache"

# Small files that must be versioned (dev/test split, my own questions) live in the repo.
EVALS_DIR = PROJECT_ROOT / "evals"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Local Postgres + pgvector from docker-compose.yml.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://filinglens:filinglens@127.0.0.1:5434/filinglens")

# The SEC requires a User-Agent with real contact details ("Name email@example.com").
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT")

# The one model the whole project uses (baselines included, so comparisons are fair).
MODEL = "claude-haiku-5-5"
# How much the model "thinks" before answering. Low = cheapest and fastest.
DEFAULT_EFFORT = "low"

# Claude Haiku 5.5 prices in dollars per 1M tokens. Prompts over 100K input tokens
# are billed at the higher "long context" rate for the whole request.
LONG_CONTEXT_THRESHOLD = 100_000
PRICES = {
    "standard": {"input": 0.10, "output": 0.50},
    "long": {"input": 0.50, "output": 2.50},
}


def require_anthropic_key() -> str:
    """Return the API key, or fail loudly with a helpful message."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-..."):
        raise RuntimeError("ANTHROPIC_API_KEY is missing. Copy .env.example to .env and add your key.")
    return ANTHROPIC_API_KEY
