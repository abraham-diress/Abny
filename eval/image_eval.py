"""Image eval: how good are the hero images, and can we trust the automatic scorer?

    python eval/image_eval.py                          # summarize data/runs/hero_log.jsonl
    python eval/image_eval.py --sheet                  # also write a rating sheet (HTML) to rate by hand
    python eval/image_eval.py --ratings ratings.csv    # compare the scorer with hand ratings

ratings.csv columns: hero,good   (hero = URL path from the log, good = 1 if a person would show it, else 0)
Rate about 10 images: if the scorer's pass/fail agrees with people most of the time, quote its numbers.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.conventions import MEDIA_DIR, RUNS_DIR  # noqa: E402

LOG = RUNS_DIR / "hero_log.jsonl"


def load_log() -> list[dict]:
    if not LOG.exists():
        return []
    return [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"attempts": 0}
    sc = [r["score"] for r in rows]
    by_layout: dict[str, list[dict]] = {}
    for r in rows:
        by_layout.setdefault(r["layout_id"], []).append(r)
    best_passed = sum(1 for rs in by_layout.values() if any(x["score"]["passed"] for x in rs))
    return {
        "attempts": len(rows),
        "layouts": len(by_layout),
        "attempt_pass_pct": round(100 * sum(s["passed"] for s in sc) / len(sc), 1),
        "layouts_with_a_passing_hero_pct": round(100 * best_passed / len(by_layout), 1),
        "mean_structure_preserved": round(statistics.mean(s["structure_preserved"] for s in sc), 3),
        "mean_plan_adherence": round(statistics.mean(s["plan_adherence"] for s in sc), 3),
        "mean_realism_1to5": round(statistics.mean(s["realism_1to5"] for s in sc), 2),
        "realism_scored": not any("Realism not scored" in " ".join(s["notes"]) for s in sc),
        "modes": {m: sum(1 for r in rows if r["mode"] == m) for m in {r["mode"] for r in rows}},
    }


def compare(rows: list[dict], ratings_csv: Path) -> dict:
    by_hero = {r["hero"]: r for r in rows}
    pairs = []
    with open(ratings_csv) as f:
        for rec in csv.DictReader(f):
            r = by_hero.get(rec["hero"].strip())
            if r is not None:
                pairs.append((bool(int(rec["good"])), r["score"]["passed"]))
    if not pairs:
        return {"rated": 0}
    agree = sum(1 for human, auto in pairs if human == auto)
    false_pass = sum(1 for human, auto in pairs if auto and not human)
    return {"rated": len(pairs), "agreement_pct": round(100 * agree / len(pairs), 1), "scorer_passed_bad_images": false_pass}


def write_sheet(rows: list[dict]) -> Path:
    out = MEDIA_DIR / "eval" / "hero_sheet.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    cards = []
    for r in rows:
        s = r["score"]
        cards.append(
            f"<figure><div class='row'><img src='../../../{html.escape(r['pano'].replace('media/', 'data/media/'))}'>"
            f"<img src='../../../{html.escape(r['guide'].replace('media/', 'data/media/'))}'>"
            f"<img src='../../../{html.escape(r['hero'].replace('media/', 'data/media/'))}'></div>"
            f"<figcaption><code>{html.escape(r['hero'])}</code> · {r['mode']} · structure {s['structure_preserved']} · "
            f"plan {s['plan_adherence']} · realism {s['realism_1to5']} · <b>{'PASS' if s['passed'] else 'fail'}</b></figcaption></figure>"
        )
    out.write_text(
        "<!doctype html><meta charset='utf-8'><title>Hero images</title>"
        "<style>body{font-family:system-ui;margin:16px}figure{margin:0 0 24px}.row{display:flex;gap:6px}"
        ".row img{width:32%;height:auto}code{font-size:12px}</style>"
        "<h1>Hero images: real room · plan · generated</h1><p>Write hero,good (1/0) rows into ratings.csv.</p>"
        + "".join(cards)
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", type=Path)
    ap.add_argument("--sheet", action="store_true")
    args = ap.parse_args()
    rows = load_log()
    result = {"summary": summarize(rows)}
    if args.ratings:
        result["vs_people"] = compare(rows, args.ratings)
    print(json.dumps(result, indent=2))
    if args.sheet and rows:
        print(f"Rating sheet: {write_sheet(rows)} (open it from the repo root)")
    if not rows:
        print(f"No hero attempts logged yet ({LOG}). Run render_hero on a few spaces first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
