from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import trimesh

from agent.layout.catalog import load_catalog
from agent.layout.planner import plan_layout
from agent.staging import generate, stability
from agent.staging.camera import PanoCamera
from agent.staging.files import mask_url_for, to_path, to_url
from agent.staging.guide import count_visible, render_floorplan, render_guide
from agent.staging.score import score_arrays
from shared.conventions import ASSETS_DIR, MEDIA_DIR
from shared.schemas import PanoRef

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def pano_file(tmp_path, monkeypatch):
    """A fake 'room photo': gray walls, darker floor, a window."""
    (MEDIA_DIR / "test").mkdir(parents=True, exist_ok=True)
    img = np.full((640, 640, 3), 200, np.uint8)
    img[400:] = (120, 130, 140)
    cv2.rectangle(img, (60, 120), (260, 330), (235, 225, 200), -1)
    cv2.rectangle(img, (60, 120), (260, 330), (60, 60, 60), 4)
    path = MEDIA_DIR / "test" / "room_front.png"
    cv2.imwrite(str(path), img)
    yield to_url(path)


def _pano(url: str) -> PanoRef:
    # Camera at the back of the single room looking toward the entrance (-z), 1.55 m up.
    # Matterport camera frame (calibrated at G4): z-up, front looks +x. This rotation maps that
    # frame to front = -z, up = +y in model space; real scans have almost exactly this quaternion.
    return PanoRef(pano_id="P1", space_id="S1", scan_id="scan1", face="front", path=url, defurnished=True,
                   position_m=(4.5, 1.55, 11.0), rotation_quat=(-0.5, 0.5, 0.5, 0.5), fov_deg=90, width_px=640, height_px=640)


def test_point_straight_ahead_projects_to_center(pano_file):
    cam = PanoCamera(_pano(pano_file))
    px, ok = cam.project(np.array([[4.5, 1.55, 5.0]]))
    assert ok[0] and px[0] == pytest.approx([320, 320])
    _, ok_behind = cam.project(np.array([[4.5, 1.55, 12.0]]))
    assert not ok_behind[0]


def test_render_guide_writes_guide_and_mask(single_room, bakery_brief, pano_file):
    layout = plan_layout("S1", single_room, None, bakery_brief)
    pano = _pano(pano_file)
    assert count_visible(layout, pano) >= 3
    url = render_guide(layout, pano)
    guide = cv2.imread(str(to_path(url)))
    mask = cv2.imread(str(to_path(mask_url_for(url))), cv2.IMREAD_GRAYSCALE)
    assert guide.shape == (640, 640, 3)
    assert 0.02 < (mask > 0).mean() < 0.9


def test_floorplan(single_room, bakery_brief):
    layout = plan_layout("S1", single_room, None, bakery_brief)
    url = render_floorplan(layout, single_room)
    assert url.startswith("media/guides/") and to_path(url).exists()


def test_scorer_identical_images_have_perfect_structure_and_no_new_furniture():
    rng = np.random.default_rng(0)
    img = cv2.GaussianBlur((rng.random((400, 400, 3)) * 255).astype(np.uint8), (7, 7), 0)
    mask = np.zeros((400, 400), np.uint8)
    mask[250:350, 100:300] = 255
    s = score_arrays(img, img.copy(), mask, None)
    assert s.structure_preserved > 0.95
    assert s.plan_adherence < 0.1
    assert not s.passed  # nothing was added


def test_scorer_rewards_change_only_inside_mask():
    rng = np.random.default_rng(1)
    img = cv2.GaussianBlur((rng.random((400, 400, 3)) * 255).astype(np.uint8), (7, 7), 0)
    mask = np.zeros((400, 400), np.uint8)
    mask[250:350, 100:300] = 255
    gen = img.copy()
    cv2.rectangle(gen, (110, 260), (290, 340), (30, 90, 160), -1)  # "furniture"
    s = score_arrays(img, gen, mask, None)
    assert s.structure_preserved > 0.85 and s.plan_adherence > 0.8 and s.passed

    moved_walls = cv2.flip(gen, 1)
    assert score_arrays(img, moved_walls, mask, None).structure_preserved < s.structure_preserved - 0.2


def _fake_paint(image, mask, n):
    out = []
    for k in range(n):
        g = image.copy()
        m = cv2.resize(mask, (g.shape[1], g.shape[0]))
        g[m > 0] = (40 + 30 * k, 90, 150)
        out.append(g)
    return out


def test_hero_flow_with_fake_provider(single_room, bakery_brief, pano_file, monkeypatch, tmp_path):
    layout = plan_layout("S1", single_room, None, bakery_brief)
    monkeypatch.setattr(generate, "_panoramas", lambda space_id: [_pano(pano_file)])
    monkeypatch.setattr(stability, "inpaint", lambda image, mask, prompt, n=2, seed=7, **kw: _fake_paint(image, mask, n))
    monkeypatch.setattr(generate, "RUNS_DIR", tmp_path)  # keep the real hero log clean
    monkeypatch.setenv("HERO_MODE", "inpaint")
    hero = generate.render_hero("S1", layout, style="light wood and white tile")
    assert hero.score is not None and hero.score.passed
    assert to_path(hero.path).exists() and hero.guide_path
    assert "light wood" in hero.prompt
    assert "stability" in hero.model

    monkeypatch.setenv("HERO_MODE", "preview")
    preview = generate.render_hero("S1", layout)
    assert preview.model == "preview-guide" and preview.path == preview.guide_path


def test_hero_falls_back_to_preview_when_generation_fails(single_room, bakery_brief, pano_file, monkeypatch, tmp_path):
    layout = plan_layout("S1", single_room, None, bakery_brief)
    monkeypatch.setattr(generate, "_panoramas", lambda space_id: [_pano(pano_file)])
    monkeypatch.setattr(generate, "RUNS_DIR", tmp_path)

    def broken(*a, **kw):
        raise stability.StabilityError("quota exceeded")

    monkeypatch.setattr(stability, "inpaint", broken)
    monkeypatch.setenv("HERO_MODE", "inpaint")
    hero = generate.render_hero("S1", layout)
    assert hero.path == hero.guide_path and hero.score is None
    assert "quota exceeded" in hero.model


def test_prompt_names_the_furniture_this_photo_shows(single_room, bakery_brief):
    layout = plan_layout("S1", single_room, None, bakery_brief)
    tables = [i for i in layout.items if i.item_type in ("table_2", "table_4")]
    assert tables
    p = generate.build_prompt(layout, None, tables)
    assert "café tables" in p and "display case" not in p  # a photo of the seating gets tables, not a pastry case
    assert "display case" in generate.build_prompt(layout, None)  # no photo: the template's description


def test_catalog_models_exist_and_match_sizes():
    cat = load_catalog()
    rows = json.loads((ASSETS_DIR / "catalog.json").read_text())
    assert len(cat) == len(rows) >= 10
    for item in cat.values():
        path = ROOT / item.glb_asset
        assert path.exists(), item.glb_asset
        mesh = trimesh.load(path, force="mesh")
        ex, ey, ez = mesh.extents
        assert ex <= item.width_m + 0.05 and ez <= item.depth_m + 0.05, item.item_type
        assert mesh.bounds[0][1] == pytest.approx(0, abs=1e-4)


def test_floor_height_ignores_unset_room_floor(single_room, bakery_brief, pano_file, monkeypatch):
    import sys
    import types

    from agent.staging import guide

    layout = plan_layout("S1", single_room, None, bakery_brief)
    fake = types.ModuleType("pipeline.queries")
    fake.get_rooms = lambda space_id: single_room  # floor_y_m left at the default 0.0
    monkeypatch.setitem(sys.modules, "pipeline", types.ModuleType("pipeline"))
    monkeypatch.setitem(sys.modules, "pipeline.queries", fake)
    high_cam = _pano(pano_file).model_copy(update={"position_m": (4.5, 11.55, 11.0)})  # floor really at y = 10
    assert guide._floor_y(layout, high_cam) == pytest.approx(10.0)
    assert guide._floor_y(layout, _pano(pano_file)) == pytest.approx(0.0)  # consistent data is trusted


def test_cube_faces_turn_the_right_way(pano_file):
    """front looks -z here; left is a quarter turn left (-x), right (+x), back (+z)."""
    base = _pano(pano_file)
    ahead = {"front": (4.5, 1.55, 5.0), "left": (-1.5, 1.55, 11.0), "right": (10.5, 1.55, 11.0), "back": (4.5, 1.55, 17.0)}
    for face, point in ahead.items():
        px, ok = PanoCamera(base.model_copy(update={"face": face})).project(np.array([point]))
        assert ok[0] and px[0] == pytest.approx([320, 320]), face
    # A point on the floor in front of the camera is below the image center.
    px, _ = PanoCamera(base).project(np.array([[4.5, 0.0, 6.0]]))
    assert px[0][1] > 320


def test_hero_without_panoramas_is_the_floor_plan(single_room, bakery_brief, monkeypatch):
    import sys
    import types

    layout = plan_layout("S1", single_room, None, bakery_brief)
    monkeypatch.setattr(generate, "_panoramas", lambda space_id: [])
    fake = types.ModuleType("pipeline.queries")
    fake.get_rooms = lambda space_id: single_room
    monkeypatch.setitem(sys.modules, "pipeline.queries", fake)
    hero = generate.render_hero("S1", layout)
    assert hero.model.startswith("floor-plan") and hero.path.endswith("_plan.png") and to_path(hero.path).exists()
