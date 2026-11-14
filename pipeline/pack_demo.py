"""Zip the demo data so teammates can use it without the sponsor keys.

    python -m pipeline.pack_demo                 # demo spaces (candidates.priority = 0) only
    python -m pipeline.pack_demo --all-media     # everything cached under data/media
    python -m pipeline.pack_demo --out D:/share/hestia-demo.zip

The zip holds paths relative to the repo root (data/hestia.duckdb, data/media/...), so a teammate
unzips it in their repo root and the code finds it with no settings. The packed database is a copy
whose pano/aerial rows only point at files inside the zip.

Sponsor data is licensed for the hackathon only: share the zip privately (team DM / private Drive
link), never in git or a public channel.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from shared.conventions import DATA_DIR, REPO_ROOT

from pipeline.db import connect, db_path, rows

README = """Hestia demo data ({stamp})
=================================

Unzip this file in the ROOT of your hestia repo clone. It creates:
  data/hestia.duckdb      the database (spaces, rooms, panoramas, neighborhood data)
  data/media/...          panorama photos and aerial images

No settings needed: the code reads data/hestia.duckdb by default.
(If you set HESTIA_DB_PATH for the sample database, unset it.)

Demo spaces:
{spaces}

Rules: CoStar, Matterport and Vexcel data is licensed for the hackathon only.
data/ is gitignored; never commit it, never post this zip publicly.
"""


def demo_spaces() -> list[dict]:
    with connect() as con:
        return rows(con, """SELECT s.space_id, s.address, s.matterport_model_id AS model_id, s.space_use
                            FROM candidates c JOIN spaces s USING (space_id)
                            WHERE c.priority = 0 ORDER BY s.space_use, s.space_id""")


def build(out: Path, all_media: bool) -> Path:
    demos = demo_spaces()
    if not demos:
        raise SystemExit("No demo spaces. Mark them first: python -m pipeline.cache_status --set-demo id1,id2,...")
    models = sorted({d["model_id"] for d in demos if d["model_id"]})
    ids = [d["space_id"] for d in demos]

    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "hestia.duckdb"
        shutil.copy2(db_path(), db_copy)
        wal = db_path().with_name(db_path().name + ".wal")  # unflushed writes, if a writer didn't checkpoint
        if wal.exists():
            shutil.copy2(wal, db_copy.with_name(db_copy.name + ".wal"))
        with connect(read_only=False, path=db_copy) as con:
            if not all_media:  # keep only rows whose files go in the zip
                con.execute(f"DELETE FROM mp_panos WHERE model_id NOT IN ({', '.join('?' * len(models))})", models)
                con.execute(f"""UPDATE vx_props SET ortho_path = NULL, oblique_path = NULL
                                WHERE space_id NOT IN ({', '.join('?' * len(ids))})""", ids)
            con.execute("UPDATE mp_fetch_log SET raw_json = NULL")  # big and not needed at runtime
            panos = [r[0] for r in con.execute("SELECT path FROM mp_panos").fetchall()]
            aerials = [p for r in con.execute("SELECT ortho_path, oblique_path FROM vx_props").fetchall() for p in r if p]
            con.execute("CHECKPOINT")

        files = sorted({p for p in panos + aerials if (DATA_DIR / p).exists()})
        missing = len(set(panos + aerials)) - len(files)
        out.parent.mkdir(parents=True, exist_ok=True)
        spaces_txt = "\n".join(f"  {d['space_id']:<24} {d['space_use'] or '':<7} {d['address']}" for d in demos)
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("HESTIA_DEMO_DATA_README.txt", README.format(stamp=f"{datetime.now():%Y-%m-%d %H:%M}", spaces=spaces_txt))
            z.write(db_copy, "data/hestia.duckdb", compress_type=zipfile.ZIP_DEFLATED)
            for p in files:  # JPEGs are already compressed: store them
                z.write(DATA_DIR / p, f"data/{p}", compress_type=zipfile.ZIP_STORED)

    size = out.stat().st_size / 1e6
    print(f"Wrote {out} ({size:,.0f} MB): database + {len(files)} media files for {len(demos)} demo spaces"
          + (f"; {missing} referenced files were not on disk" if missing else ""))
    print(spaces_txt)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all-media", action="store_true", help="include every cached pano/aerial, not just the demo spaces")
    ap.add_argument("--out", type=Path, default=DATA_DIR / f"hestia-demo-data-{datetime.now():%Y%m%d-%H%M}.zip")
    a = ap.parse_args()
    out = a.out if a.out.is_absolute() else REPO_ROOT / a.out
    build(out, a.all_media)


if __name__ == "__main__":
    main()
