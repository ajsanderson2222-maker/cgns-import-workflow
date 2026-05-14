#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_CGNS="${ROOT_DIR}/input/mesh.cgns"
OUTPUT_MSH="${ROOT_DIR}/mesh.msh"
export ROOT_DIR

if [[ ! -f "${INPUT_CGNS}" ]]; then
    echo "Missing input mesh: ${INPUT_CGNS}" >&2
    exit 1
fi

if ! command -v gmshToFoam >/dev/null 2>&1; then
    echo "gmshToFoam is not available in PATH." >&2
    exit 1
fi

python3 - <<'PY'
import os
import meshio
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
inp = root / "input" / "mesh.cgns"
out = root / "mesh.msh"

mesh = meshio.read(inp)
mesh.write(out, file_format="gmsh22")
print(f"Wrote {out}")
PY

gmshToFoam "${OUTPUT_MSH}"
checkMesh
