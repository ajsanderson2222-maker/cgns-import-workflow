#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
source /usr/share/openfoam/etc/bashrc
rhoSimpleFoam > log.rhoSimpleFoam 2>&1
