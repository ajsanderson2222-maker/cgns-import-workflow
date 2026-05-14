#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE_DIR="${ROOT_DIR}/axi_test_case"
INPUT_CGNS="${ROOT_DIR}/Axi_Test.cgns"

"${ROOT_DIR}/.venv/bin/python" \
    "${ROOT_DIR}/import_axi_cgns_to_wedge_foam.py" \
    "${INPUT_CGNS}" \
    "${CASE_DIR}"
