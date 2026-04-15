"""
Few-shot example loader.

Returns verified working FLE Python code snippets for each category.
These are injected into agent system prompts to bootstrap correct behaviour.
"""
import importlib
import pathlib
from typing import Literal

Category = Literal["mining", "smelting", "crafting", "placement", "logistics"]

_CATEGORY_MAP: dict[str, str] = {
    "mining": "few_shot.mining",
    "smelting": "few_shot.smelting",
    "crafting": "few_shot.crafting",
    "placement": "few_shot.placement",
    "logistics": "few_shot.logistics",
}


def get_examples(category: str) -> str:
    """Return the docstring/source of the examples module for *category*."""
    if category not in _CATEGORY_MAP:
        raise ValueError(f"Unknown category '{category}'. Choose from: {list(_CATEGORY_MAP)}")
    module = importlib.import_module(_CATEGORY_MAP[category])
    return module.__doc__ or ""


def get_example_source(category: str) -> str:
    """Return the raw source text of the examples file."""
    module_name = _CATEGORY_MAP.get(category)
    if module_name is None:
        raise ValueError(f"Unknown category '{category}'")
    parts = module_name.split(".")
    src_path = pathlib.Path(__file__).parent / f"{parts[-1]}.py"
    return src_path.read_text()


__all__ = ["get_examples", "get_example_source", "Category"]
