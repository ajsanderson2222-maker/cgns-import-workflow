#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE_DIR="${ROOT_DIR}/cube_tet_case"
INPUT_CGNS="${ROOT_DIR}/cube_tet.cgns"

rm -rf "${CASE_DIR}"
"${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/import_cgns_to_foam.py" "${INPUT_CGNS}" "${CASE_DIR}"
source /usr/share/openfoam/etc/bashrc
checkMesh -case "${CASE_DIR}"
