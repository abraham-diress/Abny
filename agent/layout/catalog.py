"""Load assets/catalog.json (the furniture/equipment the planner can place)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shared.conventions import CATALOG_PATH
from shared.schemas import CatalogItem


@lru_cache(maxsize=4)
def load_catalog(path: Path = CATALOG_PATH) -> dict[str, CatalogItem]:
    """item_type -> CatalogItem. Raises if the file is missing or has duplicate types."""
    items = [CatalogItem.model_validate(row) for row in json.loads(Path(path).read_text())]
    by_type: dict[str, CatalogItem] = {}
    for item in items:
        if item.item_type in by_type:
            raise ValueError(f"Duplicate item_type {item.item_type!r} in {path}")
        by_type[item.item_type] = item
    return by_type


def catalog_list(path: Path = CATALOG_PATH) -> list[CatalogItem]:
    """Catalog as a list (what GET /api/catalog should return)."""
    return list(load_catalog(path).values())
