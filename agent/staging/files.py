"""URL path <-> file path for media/ and assets/ (see shared/conventions.py)."""

from __future__ import annotations

from pathlib import Path

from shared.conventions import ASSETS_DIR, GUIDES_DIR, HEROES_DIR, MEDIA_DIR

_ROOTS = {"media": MEDIA_DIR, "assets": ASSETS_DIR}


def to_path(url: str) -> Path:
    """'media/...' or 'assets/...' -> file on disk. Plain file paths pass through."""
    clean = url.lstrip("/")
    prefix, _, rest = clean.partition("/")
    if prefix in _ROOTS and rest:
        root = _ROOTS[prefix].resolve()
        target = (root / rest).resolve()
        if root not in target.parents:
            raise ValueError(f"{url!r} escapes {root}")
        return target
    return Path(url)


def to_url(path: Path | str) -> str:
    """File under data/media or assets -> 'media/...' / 'assets/...'."""
    p = Path(path).resolve()
    for prefix, root in _ROOTS.items():
        try:
            return f"{prefix}/{p.relative_to(root.resolve()).as_posix()}"
        except ValueError:
            continue
    raise ValueError(f"{p} is not under {MEDIA_DIR} or {ASSETS_DIR}")


def ensure_dirs() -> None:
    for d in (GUIDES_DIR, HEROES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def mask_url_for(guide_url: str) -> str:
    """The inpainting mask saved next to a guide image."""
    return guide_url[:-4] + "_mask.png" if guide_url.endswith(".png") else guide_url + "_mask.png"
