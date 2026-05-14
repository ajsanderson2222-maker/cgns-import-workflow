# CGNS Import Workflow

This repository captures two separate `CGNS -> OpenFOAM` import paths that were
built against real STAR-style CGNS exports rather than idealized converter test
files.

The goal of the repo is not just to hold scripts. It is also a record of what
worked, what failed, why the final paths were chosen, and how each mesh family
should be handled going forward.

## Repository Scope

This repo currently covers two distinct workflows:

1. A 3D mixed-cell workflow for STAR-style CGNS files that contain tetrahedra
   and prisms.
2. A separate axisymmetric workflow for STAR-style 2D polygon meshes that must
   be turned into an OpenFOAM wedge mesh.

These are intentionally separate implementations.

- The 3D importer is for volumetric mixed-cell meshes.
- The axisymmetric importer is for 2D axisymmetric source meshes.
- The two scripts do not share logic on purpose.

That separation is important because the failure modes are different:

- the 3D path is primarily about cell-face ownership and patch mapping
- the axisymmetric path is primarily about extrusion into a valid wedge mesh

## Why This Repo Exists

The first attempted approach was the obvious one:

`CGNS -> meshio -> Gmsh .msh -> gmshToFoam`

That did not work on the provided files because the local `meshio` CGNS reader
rejected the STAR-style HDF5 CGNS layout used by the sample exports.

The practical result was:

- the sample files were valid HDF5 CGNS
- they were not readable by the local generic CGNS import stack
- OpenFOAM in this environment did not provide a native `cgnsToFoam`
- a direct importer was the shortest reliable route

This repo therefore implements direct OpenFOAM mesh writers targeted at the
specific CGNS layout actually encountered.

## Repository Layout

- `import_cgns_to_foam.py`
  Direct 3D importer for STAR-style mixed-cell CGNS files.

- `import_cube_tet.sh`
  Convenience wrapper for the 3D mixed tet+prism sample.

- `import_axi_cgns_to_wedge_foam.py`
  Separate importer for STAR-style 2D axisymmetric CGNS files.

- `import_axi_test.sh`
  Convenience wrapper for the axisymmetric sample.

- `cube_tet_case/`
  Generated OpenFOAM case for the 3D mixed-cell sample, including the imported
  `polyMesh` and a basic solver smoke-test setup.

- `axi_test_case/`
  Generated OpenFOAM wedge case for the axisymmetric sample.

- `docs/axi_test_mesh.png`
  Axisymmetric source mesh visualization used in the documentation.

- `convert.sh`
  Earlier `meshio -> gmshToFoam` attempt kept as reference, even though that is
  not the successful path used for the provided files.

## Environment Notes

The workflow was developed in:

- OpenFOAM `v1912` style environment
- local Python virtual environment in `.venv`
- `h5py`, `numpy`, `meshio`, and plotting tools available locally

One recurring environment note:

- sourcing `/usr/share/openfoam/etc/bashrc` in this environment emits
  `foamEtcFile` / `foamCleanPath` warnings
- despite those warnings, `checkMesh` and the relevant solvers still run

Those warnings are environmental noise, not workflow failures.

## Workflow A: 3D Mixed Tet+Prism Import

### Input Characteristics

The working 3D sample was `cube_tet.cgns`.

Important observations from inspection:

- it was not actually a pure tetrahedral mesh
- it contained a mixed 3D cell set
- it preserved meaningful boundary groups in CGNS

The imported mesh resolved as:

- `481` tetrahedra
- `356` prisms

The main boundary patches were:

- `inlet`
- `outlet`
- `walls`

### Why the Generic Converter Path Was Abandoned

`meshio` failed to read the file using its CGNS reader because it expected a
different zone layout. The file used a STAR-style organization that was valid
for the source toolchain but not consumable by the local generic import route.

Instead of continuing to fight intermediate formats, the repo switched to
writing OpenFOAM `polyMesh` files directly:

`CGNS -> import_cgns_to_foam.py -> OpenFOAM polyMesh`

### What the 3D Importer Does

`import_cgns_to_foam.py`:

- reads coordinates from the CGNS zone
- reads mixed-cell connectivity
- supports:
  - tetrahedra
  - prisms
  - pyramids
  - hexahedra
- reconstructs cell faces
- builds owner/neighbour addressing
- orders internal faces for OpenFOAM
- maps CGNS boundary groups into OpenFOAM patches
- writes:
  - `points`
  - `faces`
  - `owner`
  - `neighbour`
  - `boundary`

### Validation Result

The imported 3D sample passed `checkMesh`.

Observed mesh summary:

- `837` cells
- `367` points
- `2013` faces
- one connected region
- `Mesh OK`

### 3D Convenience Commands

Run the import:

```bash
cd /home/ads-user/openfoam/cgns-import-workflow
.venv/bin/python import_cgns_to_foam.py cube_tet.cgns cube_tet_case
```

Or use the wrapper:

```bash
cd /home/ads-user/openfoam/cgns-import-workflow
./import_cube_tet.sh
```

Validate the mesh:

```bash
source /usr/share/openfoam/etc/bashrc
checkMesh -case /home/ads-user/openfoam/cgns-import-workflow/cube_tet_case
```

## 3D Solver Smoke Test

A quick steady compressible verification case was also created on top of the
imported `cube_tet_case`. This was not meant to produce a trustworthy CFD
solution. It was only used to prove that the imported mesh could survive a real
OpenFOAM solver setup.

### Solver Choice

- `rhoSimpleFoam`
- steady
- laminar air

### Boundary Values Used

- inlet stagnation pressure:
  - `14.7 psia`
  - `101352.932 Pa`
- inlet stagnation temperature:
  - `518.7 R`
  - `288.1667 K`
- outlet static pressure:
  - `14.0 psia`
  - `96526.602 Pa`
- outlet backflow temperature:
  - `288.1667 K`

### Supporting Case Files

- `cube_tet_case/0/U`
- `cube_tet_case/0/p`
- `cube_tet_case/0/T`
- `cube_tet_case/constant/thermophysicalProperties`
- `cube_tet_case/constant/turbulenceProperties`
- `cube_tet_case/system/fvSchemes`
- `cube_tet_case/system/fvSolution`
- `cube_tet_case/system/fvOptions`

### Smoke-Test Outcome

What worked:

- the case ran in `rhoSimpleFoam`
- the final stabilized version advanced through `Time = 200`
- the imported mesh was usable by an actual solver

What did not:

- the solution was not quantitatively trustworthy
- the mesh was far too coarse for a serious pressure-driven compressible case
- pressure excursions remained large
- continuity error remained high
- a temperature limiter was required to keep the case from diverging

Interpretation:

- this should be treated as a runtime verification only
- it demonstrates OpenFOAM compatibility, not physical fidelity

## Workflow B: Axisymmetric CGNS to Wedge Mesh

The axisymmetric path is documented in detail in [AXI_README.md](./AXI_README.md).

Summary:

- `Axi_Test.cgns` is a true 2D axisymmetric source mesh
- all source points lie in `Z = 0`
- cells are 2D polygons
- boundaries are edges
- OpenFOAM therefore needs a separate wedge-extrusion importer

The axisymmetric importer is intentionally separate:

- do not modify the 3D importer to support this case
- do not merge the logic paths

## Unsupported / Partially Supported Cases

### Polyhedral `NGON/NFACE` Export

`cube_poly.cgns` is a different problem class.

It represents a polyhedral export using `NGON/NFACE` style connectivity. That
is not handled by the current 3D importer, which was built around mixed
tet/prism-style cell definitions rather than fully general polyhedral topology.

### Why This Matters

There are now three distinct STAR-style CGNS families seen in this work:

1. mixed 3D element mesh with explicit supported cell types
2. 2D axisymmetric polygon mesh
3. polyhedral `NGON/NFACE` mesh

Only the first two have working import paths in this repo.

## Recommended Usage Pattern

If a new file arrives, classify it before choosing an importer:

1. If it is 3D and uses explicit mixed elements:
   use `import_cgns_to_foam.py`

2. If it is 2D axisymmetric:
   use `import_axi_cgns_to_wedge_foam.py`

3. If it is fully polyhedral `NGON/NFACE`:
   treat it as unsupported for now and build a new dedicated path

That classification step matters more than the file extension.

## Current Deliverables

At this point the repo contains:

- one working 3D direct importer
- one working axisymmetric wedge importer
- one validated 3D OpenFOAM mesh case
- one validated axisymmetric wedge mesh case
- one axisymmetric source mesh image for documentation
- full notes describing the reasoning behind the implemented workflows

## Quick Start

### 3D Mixed-Cell Path

```bash
cd /home/ads-user/openfoam/cgns-import-workflow
./import_cube_tet.sh
source /usr/share/openfoam/etc/bashrc
checkMesh -case cube_tet_case
```

### Axisymmetric Path

```bash
cd /home/ads-user/openfoam/cgns-import-workflow
./import_axi_test.sh
source /usr/share/openfoam/etc/bashrc
checkMesh -case axi_test_case
```

## Final Status

This repo now demonstrates two successful direct import workflows for STAR-style
CGNS files that could not be handled cleanly by the local generic conversion
stack.

That is the main technical result:

- direct 3D mixed-cell import works
- direct axisymmetric wedge import works
- both end in OpenFOAM meshes that pass `checkMesh`
