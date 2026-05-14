# CGNS Import Workflow

This directory is isolated from the main case and is only for getting
`CGNS -> OpenFOAM` import working.

## Current status

- `cube_tet.cgns` imports successfully into OpenFOAM.
- The imported mesh contains `481` tetrahedra and `356` prisms.
- `checkMesh` passes on the generated case.
- A quick compressible smoke test also runs to completion on the imported mesh.
- `cube_poly.cgns` is a different `NGON/NFACE` polyhedral export and is not
  handled by the current importer.

## Files

- `import_cgns_to_foam.py`: direct CGNS-to-`polyMesh` importer for the
  STAR-style mixed-element export used by `cube_tet.cgns`
- `cube_tet_case/`: generated OpenFOAM case
- `cube_tet_case/0`, `constant`, `system`: minimal steady compressible test
  case on the imported mesh
- `.venv/`: isolated Python environment
- `convert.sh`: earlier `meshio -> gmshToFoam` attempt kept for reference

## Use the working path

Run the importer:

```bash
cd /home/ads-user/openfoam/cgns-import-workflow
.venv/bin/python import_cgns_to_foam.py cube_tet.cgns cube_tet_case
```

Validate the mesh:

```bash
source /usr/share/openfoam/etc/bashrc
checkMesh -case /home/ads-user/openfoam/cgns-import-workflow/cube_tet_case
```

Run the quick solver smoke test:

```bash
cd /home/ads-user/openfoam/cgns-import-workflow/cube_tet_case
./run.sh
```

## Imported tet+prism case

`cube_tet.cgns` is not a pure tet mesh. The importer reads it as:

- `481` tetrahedra
- `356` prisms
- boundary patches:
  - `walls`: `178` faces
  - `inlet`: `72` faces
  - `outlet`: `72` faces

`checkMesh` result on `cube_tet_case`:

- `837` cells
- `367` points
- `2013` faces
- single region
- `Mesh OK`

## Smoke-test run setup

Solver:

- `rhoSimpleFoam`
- steady
- laminar air

Boundary values used:

- inlet stagnation pressure: `14.7 psia = 101352.932 Pa`
- inlet stagnation temperature: `518.7 R = 288.1667 K`
- outlet static pressure: `14.0 psia = 96526.602 Pa`
- outlet temperature backflow value: `288.1667 K`

Case files:

- `0/U`: pressure-driven inlet/outlet velocity, no-slip walls
- `0/p`: `totalPressure` inlet, fixed static pressure outlet
- `0/T`: `totalTemperature` inlet, `inletOutlet` outlet
- `constant/thermophysicalProperties`: perfect-gas air
- `constant/turbulenceProperties`: `laminar`
- `system/fvOptions`: global `limitTemperature` clamp for robustness

## Smoke-test run outcome

What worked:

- the imported mesh runs in `rhoSimpleFoam`
- the case advanced from `Time = 1` through `Time = 200`
- no solver crash after the final stabilization changes

What did not:

- the solution is not trustworthy quantitatively
- the mesh is extremely coarse for this pressure-driven compressible setup
- pressure excursions are still large
- cumulative continuity error remains high
- `limitTemperature` was needed to keep the run from blowing up

Interpretation:

- this is only a runtime verification case
- it demonstrates that the imported tet+prism mesh can be used by OpenFOAM
- it should not be treated as a converged or validated CFD result

## Why the direct importer exists

The first attempted path was:

- `CGNS -> meshio -> Gmsh .msh -> gmshToFoam`

That failed because both sample CGNS files are valid HDF5 CGNS, but use a
STAR-style layout that the available `meshio` CGNS reader rejected.

The working path is:

- `CGNS -> import_cgns_to_foam.py -> OpenFOAM polyMesh`

## Notes

- The successful path does not go through `meshio` or `gmshToFoam`.
- The importer currently supports mixed-cell volume meshes built from
  `tetrahedra`, `prisms`, `pyramids`, and `hexahedra`, with `tri` and `quad`
  boundary faces.
- `cube_poly.cgns` is still a separate problem because it is an `NGON/NFACE`
  polyhedral export.
