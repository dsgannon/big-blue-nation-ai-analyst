#!/usr/bin/env bash
# scripts/retrain.sh
#
# Full retrain pipeline for Big Blue Nation AI Analyst.
#
# Steps:
#   1. Refresh ESPN data (roster, schedule, box scores, BPI)
#   2. Execute model_v2.ipynb in-place to retrain all XGBoost models
#   3. Stamp trained models with version metadata (model_registry.json)
#   4. (Optional) Run post-game validation report
#
# Usage:
#   ./scripts/retrain.sh               # standard retrain
#   ./scripts/retrain.sh --no-refresh  # skip data refresh, retrain only
#   ./scripts/retrain.sh --validate    # also print validation report after training

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
VENV_JUPYTER="$PROJECT_ROOT/venv/bin/jupyter"
NOTEBOOK="$PROJECT_ROOT/notebooks/model_v2.ipynb"
MODELS_DIR="$PROJECT_ROOT/data/models"
REGISTRY="$MODELS_DIR/model_registry.json"

# Parse flags
DO_REFRESH=1
DO_VALIDATE=0
for arg in "$@"; do
  case "$arg" in
    --no-refresh) DO_REFRESH=0 ;;
    --validate)   DO_VALIDATE=1 ;;
    --help|-h)
      echo "Usage: ./scripts/retrain.sh [--no-refresh] [--validate]"
      exit 0
      ;;
  esac
done

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "❌  Python venv not found at $VENV_PYTHON"
  echo "    Create it with:  python3 -m venv venv && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -x "$VENV_JUPYTER" ]]; then
  echo "❌  jupyter not found in venv. Install with: pip install jupyter nbconvert"
  exit 1
fi

if [[ ! -f "$NOTEBOOK" ]]; then
  echo "❌  Notebook not found: $NOTEBOOK"
  exit 1
fi

cd "$PROJECT_ROOT"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    BIG BLUE NATION AI ANALYST — MODEL RETRAIN            ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Project: $PROJECT_ROOT"
echo "║  Python:  $VENV_PYTHON"
echo "║  Date:    $(date '+%Y-%m-%d %H:%M:%S')"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Data refresh ──────────────────────────────────────────────────────
if [[ $DO_REFRESH -eq 1 ]]; then
  echo "━━━ Step 1: Data Refresh ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.ingestion.refresh import run_refresh
run_refresh()
"
  echo ""
else
  echo "━━━ Step 1: Data Refresh SKIPPED (--no-refresh) ━━━━━━━━━━━━"
  echo ""
fi

# ── Step 2: Execute training notebook ────────────────────────────────────────
echo "━━━ Step 2: Training models (executing model_v2.ipynb) ━━━━━━"
echo "    This may take a few minutes..."
"$VENV_JUPYTER" nbconvert \
  --to notebook \
  --execute \
  --inplace \
  --ExecutePreprocessor.timeout=600 \
  --ExecutePreprocessor.kernel_name=python3 \
  "$NOTEBOOK"

echo "    ✅ Notebook executed and saved in-place"
echo ""

# ── Step 3: Stamp model registry ─────────────────────────────────────────────
echo "━━━ Step 3: Updating model registry ━━━━━━━━━━━━━━━━━━━━━━━━━"

# Build registry JSON with file sizes and modification times
"$VENV_PYTHON" - <<'PYEOF'
import json, os, hashlib
from datetime import datetime

models_dir = "data/models"
registry_path = os.path.join(models_dir, "model_registry.json")

# Load existing registry to get previous entries
if os.path.exists(registry_path):
    with open(registry_path) as f:
        registry = json.load(f)
else:
    registry = {"history": []}

def sha256_short(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:12]

artifacts = {}
for fname in sorted(os.listdir(models_dir)):
    fpath = os.path.join(models_dir, fname)
    if os.path.isfile(fpath) and not fname.startswith("model_registry"):
        stat = os.stat(fpath)
        artifacts[fname] = {
            "size_kb":     round(stat.st_size / 1024, 1),
            "sha256_short": sha256_short(fpath),
            "mtime":       datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }

entry = {
    "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "artifacts":  artifacts,
}

registry["latest"] = entry
registry.setdefault("history", []).append(entry)
# Keep last 10 entries
registry["history"] = registry["history"][-10:]

with open(registry_path, "w") as f:
    json.dump(registry, f, indent=2)

print(f"  ✅ Registry updated → {registry_path}")
print(f"     {len(artifacts)} artifacts stamped at {entry['trained_at']}")
PYEOF

echo ""

# ── Step 4: Optional validation report ───────────────────────────────────────
if [[ $DO_VALIDATE -eq 1 ]]; then
  echo "━━━ Step 4: Validation Report ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.models.validation import validation_report
validation_report()
"
  echo ""
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  Retrain complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "  Commit the updated models:"
echo "    git add data/models/ && git commit -m 'chore: retrain models $(date +%Y-%m-%d)'"
echo ""
