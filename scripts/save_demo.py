"""Make a recorded run a demo recording:  python -m scripts.save_demo <run_id> [<run_id> ...]

Each recording is saved as data/runs/demo_<business_type>.json (demo_bakery.json, demo_office.json),
which is what DEMO=1 / DEMO_REPLAY=office replay for briefs of that type.
"""

import json
import shutil
import sys

from server.runs import recording_type
from shared.conventions import RUNS_DIR

if len(sys.argv) < 2:
    sys.exit(__doc__)
for run_id in sys.argv[1:]:
    src = RUNS_DIR / f"{run_id}.json"
    if not src.is_file():
        sys.exit(f"no recording at {src}")
    btype = recording_type(json.loads(src.read_text())) or "bakery"
    dst = RUNS_DIR / f"demo_{btype}.json"
    shutil.copy(src, dst)
    print(f"{src} -> {dst}")
