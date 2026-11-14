"""Data Engine (owner: Natnael): CoStar/Matterport/Vexcel -> DuckDB + media cache, and query functions.

Entry points (run from the repo root):
    python -m pipeline.sample_data           # synthetic DB so everyone can build at M0
    python -m pipeline.ingest_costar         # CoStar dump -> DuckDB tables + `spaces`
    python -m pipeline.gates                 # kickoff checks G1 + G4
    python -m pipeline.fetch_matterport      # rooms, scan poses, panorama faces
    python -m pipeline.fetch_vexcel          # property data + aerial crops
    python -m pipeline.fetch_transit         # transit stops (OpenStreetMap)
    python -m pipeline.cache_status          # what's cached per space (demo check)
"""
