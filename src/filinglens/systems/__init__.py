"""Registry of answering systems, looked up by name from the eval runner."""
from __future__ import annotations

from importlib import import_module

from filinglens.systems.base import System, SystemAnswer

# name -> "module:function". Imported lazily so heavy deps (embeddings) load only when used.
_REGISTRY = {
    "oracle": "filinglens.systems.oracle:answer",
    "long_context": "filinglens.systems.long_context:answer",
    "naive_rag": "filinglens.systems.naive_rag:answer",
}


def get_system(name: str) -> System:
    if name not in _REGISTRY:
        raise SystemExit(f"Unknown system {name!r}. Choose from: {', '.join(_REGISTRY)}")
    module, func = _REGISTRY[name].split(":")
    return getattr(import_module(module), func)


__all__ = ["System", "SystemAnswer", "get_system"]
