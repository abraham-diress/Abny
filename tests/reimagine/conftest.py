"""Hand-made rooms and panoramas for the Reimaginer tests."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.schemas import Brief, Opening, Room  # noqa: E402


def rotate(points, deg, offset=(0.0, 0.0)):
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return [(round(x * c - z * s + offset[0], 4), round(x * s + z * c + offset[1], 4)) for x, z in points]


@pytest.fixture
def bakery_brief() -> Brief:
    return Brief(raw_text="bakery with two ovens, 20 seats", business_type="bakery", seats_wanted=20)


@pytest.fixture
def single_room() -> list[Room]:
    return [
        Room(
            room_id="R1",
            space_id="S1",
            polygon_m=[(0, 0), (9, 0), (9, 12), (0, 12)],
            area_m2=108,
            openings=[
                Opening(kind="door", a=(4, 0), b=(5, 0)),
                Opening(kind="window", a=(0.5, 0), b=(3.7, 0)),
                Opening(kind="window", a=(5.3, 0), b=(8.5, 0)),
            ],
        )
    ]


@pytest.fixture
def front_and_kitchen() -> list[Room]:
    return [
        Room(
            room_id="F",
            space_id="S2",
            polygon_m=[(0, 0), (8, 0), (8, 7), (0, 7)],
            area_m2=56,
            openings=[
                Opening(kind="door", a=(3.5, 0), b=(4.5, 0)),
                Opening(kind="window", a=(0.5, 0), b=(3.2, 0)),
                Opening(kind="opening", a=(6, 7), b=(7, 7)),
            ],
        ),
        Room(room_id="K", space_id="S2", room_type="kitchen", polygon_m=[(0, 7), (8, 7), (8, 11), (0, 11)], area_m2=32),
    ]


@pytest.fixture
def rotated_l() -> list[Room]:
    shape = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 11), (0, 11)]
    off = (100.0, 50.0)
    return [
        Room(
            room_id="L",
            space_id="S3",
            polygon_m=rotate(shape, 33, off),
            area_m2=80,
            openings=[Opening(kind="door", a=rotate([(6, 0)], 33, off)[0], b=rotate([(7, 0)], 33, off)[0])],
        )
    ]
