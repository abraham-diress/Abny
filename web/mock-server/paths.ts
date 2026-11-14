import path from "node:path";

/** web/mock-server */
export const MOCK_DIR = __dirname;
export const REPO_ROOT = path.resolve(__dirname, "..", "..");

/** Everything the mock generates (gitignored). Mirrors the real folder layout of shared/conventions.py. */
export const GENERATED_DIR = path.join(MOCK_DIR, ".generated");
export const MOCK_ASSETS_DIR = path.join(GENERATED_DIR, "assets"); // like <repo>/assets
export const MOCK_MEDIA_DIR = path.join(GENERATED_DIR, "media"); // like <repo>/data/media

/** Real outputs, used first when they exist: Yared's committed assets, Natnael's/Yared's media cache. */
export const REAL_ASSETS_DIR = path.join(REPO_ROOT, "assets");
export const REAL_MEDIA_DIR = path.join(REPO_ROOT, "data", "media");
