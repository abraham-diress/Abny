"""Gate G3: is AI-generated furniture good enough to show judges? (~15 minutes, needs AWS Bedrock access)

    python eval/g3_image_test.py --images room1.jpg room2.jpg room3.jpg room4.jpg room5.jpg
    python eval/g3_image_test.py --images ... --flip-mask   # if furniture appears OUTSIDE the box, rerun with this

For each photo of an empty room (a panorama face from Matterport, or any interior photo):
* mask the lower-middle of the room (where a counter and tables would go),
* run Nova Canvas twice: inpaint (repaint only the masked area) and condition (edges of a sketch),
* score both and write a contact sheet: data/media/g3/index.html

Decision: keep the photoreal hero if at least 3 of 5 rooms have a result you would show a judge.
Otherwise set HERO_MODE=preview and lean on the 3D tour. Post the result in the team chat.
"""

from __future__ import annotations

import argparse
import html
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.staging import nova  # noqa: E402
from agent.staging.score import score_arrays  # noqa: E402
from shared.conventions import MEDIA_DIR  # noqa: E402

PROMPT = (
    "Photorealistic interior photograph of an artisan bakery: a glass pastry display case full of bread and "
    "pastries, a wooden service counter, small café tables with chairs, warm natural daylight, realistic scale. "
    "Keep the existing walls, windows, floor and ceiling exactly as they are."
)


def sketch_and_mask(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    counter = np.array([[int(w * 0.25), int(h * 0.62)], [int(w * 0.75), int(h * 0.62)], [int(w * 0.8), int(h * 0.82)], [int(w * 0.2), int(h * 0.82)]])
    tables = [(int(w * 0.18), int(h * 0.88)), (int(w * 0.5), int(h * 0.9)), (int(w * 0.82), int(h * 0.88))]
    cv2.fillPoly(mask, [counter], 255)
    for cx, cy in tables:
        cv2.ellipse(mask, (cx, cy), (int(w * 0.09), int(h * 0.05)), 0, 0, 360, 255, -1)
    sketch = img.copy()
    cv2.fillPoly(sketch, [counter], (40, 160, 235))
    for cx, cy in tables:
        cv2.ellipse(sketch, (cx, cy), (int(w * 0.09), int(h * 0.05)), 0, 0, 360, (90, 170, 70), -1)
    sketch = cv2.addWeighted(sketch, 0.5, img, 0.5, 0)
    return sketch, mask


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="+", required=True, type=Path)
    ap.add_argument("--flip-mask", action="store_true", help="invert Nova mask polarity")
    args = ap.parse_args()
    if args.flip_mask:
        os.environ["NOVA_MASK_BLACK_IS_EDIT"] = "0"

    out_dir = MEDIA_DIR / "g3"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, path in enumerate(args.images):
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            print(f"skip {path}: not an image")
            continue
        img = nova.fit_size(img)
        sketch, mask = sketch_and_mask(img)
        cv2.imwrite(str(out_dir / f"{i}_room.png"), img)
        cv2.imwrite(str(out_dir / f"{i}_sketch.png"), sketch)
        cells = []
        for mode in ("inpaint", "condition"):
            try:
                gen = (nova.inpaint(img, mask, PROMPT, n=1) if mode == "inpaint" else nova.conditioned(sketch, PROMPT, n=1))[0]
                gen = cv2.resize(gen, (img.shape[1], img.shape[0]))
                cv2.imwrite(str(out_dir / f"{i}_{mode}.png"), gen)
                s = score_arrays(img, gen, mask, sketch)
                cells.append((mode, f"{i}_{mode}.png", f"structure {s.structure_preserved} · plan {s.plan_adherence} · realism {s.realism_1to5}"))
                print(f"{path.name} {mode}: {s}")
            except nova.NovaError as exc:
                cells.append((mode, None, html.escape(str(exc))[:300]))
                print(f"{path.name} {mode}: FAILED {exc}")
        rows.append((i, path.name, cells))

    parts = ["<!doctype html><meta charset='utf-8'><title>G3 image test</title>",
             "<style>body{font-family:system-ui;margin:16px}.row{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:28px}"
             "img{width:100%}small{color:#555}</style><h1>Gate G3: room · sketch · inpaint · condition</h1>",
             "<p>Keep the photoreal hero if at least 3 of 5 rooms have a result you'd show a judge.</p>"]
    for i, name, cells in rows:
        parts.append(f"<h3>{html.escape(name)}</h3><div class='row'><img src='{i}_room.png'><img src='{i}_sketch.png'>")
        for mode, file, note in cells:
            parts.append(f"<div>{f'<img src={chr(39)}{file}{chr(39)}>' if file else ''}<small><b>{mode}</b> {note}</small></div>")
        parts.append("</div>")
    (out_dir / "index.html").write_text("".join(parts))
    print(f"\nContact sheet: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
