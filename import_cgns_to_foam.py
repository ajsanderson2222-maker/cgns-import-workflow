#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import h5py
import numpy as np


ELEMENT_SIZES = {
    5: 3,   # TRI_3
    7: 4,   # QUAD_4
    10: 4,  # TETRA_4
    12: 5,  # PYRA_5
    14: 6,  # PENTA_6
    17: 8,  # HEXA_8
}


@dataclass
class Cell:
    cell_type: int
    nodes: list[int]


@dataclass
class PatchInfo:
    name: str
    patch_type: str
    faces: list[tuple[int, ...]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a STAR-style CGNS mesh into an OpenFOAM polyMesh."
    )
    parser.add_argument("input_cgns", type=Path)
    parser.add_argument("case_dir", type=Path)
    return parser.parse_args()


def decode_cgns_string(dataset: h5py.Dataset) -> str:
    data = dataset[()]
    if isinstance(data, bytes):
        return data.decode()
    if hasattr(data, "tobytes"):
        return data.tobytes().decode(errors="ignore").rstrip("\x00")
    return str(data)


def element_stream(conn: np.ndarray, offsets: np.ndarray | None, fixed_size: int | None) -> Iterable[np.ndarray]:
    if offsets is not None:
        for start, end in zip(offsets[:-1], offsets[1:]):
            yield conn[int(start):int(end)]
        return

    if fixed_size is None:
        raise ValueError("Need either offsets or fixed element size to parse connectivity.")

    step = 1 + fixed_size
    for start in range(0, len(conn), step):
        yield conn[start:start + step]


def read_points(zone: h5py.Group) -> np.ndarray:
    coords = []
    for axis in ("CoordinateX", "CoordinateY", "CoordinateZ"):
        coords.append(zone["GridCoordinates"][axis][" data"][()])
    return np.column_stack(coords)


def read_cells(zone: h5py.Group) -> list[Cell]:
    elem_group = zone["Region"]
    conn = elem_group["ElementConnectivity"][" data"][()]
    offsets = elem_group["ElementStartOffset"][" data"][()]
    cells: list[Cell] = []
    for elem in element_stream(conn, offsets, None):
        cell_type = int(elem[0])
        if cell_type not in (10, 12, 14, 17):
            raise ValueError(f"Unsupported cell type {cell_type} in volume region.")
        cells.append(Cell(cell_type=cell_type, nodes=[int(v) - 1 for v in elem[1:]]))
    return cells


def read_patches(zone: h5py.Group) -> list[PatchInfo]:
    zone_bc = zone["ZoneBC"]
    patches: list[PatchInfo] = []

    for patch_name in zone_bc:
        bc = zone_bc[patch_name]
        elem_group = zone[patch_name]
        elem_type_header = int(elem_group[" data"][()][0])
        conn = elem_group["ElementConnectivity"][" data"][()]
        offsets = elem_group["ElementStartOffset"][" data"][()] if "ElementStartOffset" in elem_group else None
        fixed_size = None if elem_type_header == 20 else ELEMENT_SIZES[elem_type_header]

        faces = []
        if elem_type_header == 20:
            for elem in element_stream(conn, offsets, None):
                face_type = int(elem[0])
                if face_type not in (5, 7):
                    raise ValueError(f"Unsupported boundary face type {face_type} in patch {patch_name}.")
                faces.append(tuple(int(v) - 1 for v in elem[1:]))
        else:
            if fixed_size is None:
                raise ValueError(f"Unsupported fixed boundary type header {elem_type_header} in patch {patch_name}.")
            for start in range(0, len(conn), fixed_size):
                face = conn[start:start + fixed_size]
                faces.append(tuple(int(v) - 1 for v in face))

        cgns_bc_type = decode_cgns_string(bc[" data"])
        foam_type = {
            "BCWall": "wall",
        }.get(cgns_bc_type, "patch")

        clean_name = patch_name.split(".")[-1].lower()
        patches.append(PatchInfo(name=clean_name, patch_type=foam_type, faces=faces))

    return patches


def cell_faces(cell: Cell) -> list[list[int]]:
    n = cell.nodes
    if cell.cell_type == 10:
        return [
            [n[0], n[2], n[1]],
            [n[0], n[1], n[3]],
            [n[1], n[2], n[3]],
            [n[2], n[0], n[3]],
        ]
    if cell.cell_type == 12:
        return [
            [n[0], n[3], n[2], n[1]],
            [n[0], n[1], n[4]],
            [n[1], n[2], n[4]],
            [n[2], n[3], n[4]],
            [n[3], n[0], n[4]],
        ]
    if cell.cell_type == 14:
        return [
            [n[0], n[2], n[1]],
            [n[3], n[4], n[5]],
            [n[0], n[1], n[4], n[3]],
            [n[1], n[2], n[5], n[4]],
            [n[2], n[0], n[3], n[5]],
        ]
    if cell.cell_type == 17:
        return [
            [n[0], n[3], n[2], n[1]],
            [n[4], n[5], n[6], n[7]],
            [n[0], n[1], n[5], n[4]],
            [n[1], n[2], n[6], n[5]],
            [n[2], n[3], n[7], n[6]],
            [n[3], n[0], n[4], n[7]],
        ]
    raise ValueError(f"Unsupported cell type {cell.cell_type}.")


def face_center(points: np.ndarray, face_nodes: list[int]) -> np.ndarray:
    return points[np.array(face_nodes)].mean(axis=0)


def face_normal(points: np.ndarray, face_nodes: list[int]) -> np.ndarray:
    origin = points[face_nodes[0]]
    normal = np.zeros(3)
    for i in range(1, len(face_nodes) - 1):
        a = points[face_nodes[i]] - origin
        b = points[face_nodes[i + 1]] - origin
        normal += np.cross(a, b)
    return normal


def orient_outward(points: np.ndarray, face_nodes: list[int], cell_center: np.ndarray) -> list[int]:
    center = face_center(points, face_nodes)
    normal = face_normal(points, face_nodes)
    if np.dot(normal, cell_center - center) > 0:
        return list(reversed(face_nodes))
    return face_nodes


def foam_header(cls: str, obj: str) -> str:
    return f"""/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:                                        |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    location    "constant/polyMesh";
    object      {obj};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

"""


def write_points(path: Path, points: np.ndarray) -> None:
    with path.open("w", encoding="ascii") as f:
        f.write(foam_header("vectorField", "points"))
        f.write(f"{len(points)}\n(\n")
        for x, y, z in points:
            f.write(f"({x:.16g} {y:.16g} {z:.16g})\n")
        f.write(")\n\n// ************************************************************************* //\n")


def write_faces(path: Path, faces: list[list[int]]) -> None:
    with path.open("w", encoding="ascii") as f:
        f.write(foam_header("faceList", "faces"))
        f.write(f"{len(faces)}\n(\n")
        for face in faces:
            f.write(f"{len(face)}(" + " ".join(str(v) for v in face) + ")\n")
        f.write(")\n\n// ************************************************************************* //\n")


def write_label_list(path: Path, obj: str, values: list[int], note: str) -> None:
    with path.open("w", encoding="ascii") as f:
        f.write(foam_header(f"labelList", obj))
        f.write(f"{note}\n")
        f.write(f"{len(values)}\n(\n")
        for value in values:
            f.write(f"{value}\n")
        f.write(")\n\n// ************************************************************************* //\n")


def write_boundary(path: Path, patch_entries: list[tuple[str, str, int, int]]) -> None:
    with path.open("w", encoding="ascii") as f:
        f.write(foam_header("polyBoundaryMesh", "boundary"))
        f.write(f"{len(patch_entries)}\n(\n")
        for name, patch_type, n_faces, start_face in patch_entries:
            f.write(f"    {name}\n")
            f.write("    {\n")
            f.write(f"        type            {patch_type};\n")
            if patch_type == "wall":
                f.write("        inGroups        1(wall);\n")
            f.write(f"        nFaces          {n_faces};\n")
            f.write(f"        startFace       {start_face};\n")
            f.write("    }\n")
        f.write(")\n\n// ************************************************************************* //\n")


def write_control_dict(case_dir: Path) -> None:
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True, exist_ok=True)
    path = system_dir / "controlDict"
    path.write_text(
        """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:                                        |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}

application     checkMesh;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         1;
deltaT          1;
writeControl    timeStep;
writeInterval   1;
purgeWrite      0;
writeFormat     ascii;
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable false;
""",
        encoding="ascii",
    )

    (system_dir / "fvSchemes").write_text(
        """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:                                        |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}

ddtSchemes
{
    default         steadyState;
}

gradSchemes
{
    default         Gauss linear;
}

divSchemes
{
    default         none;
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}
""",
        encoding="ascii",
    )

    (system_dir / "fvSolution").write_text(
        """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:                                        |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}

solvers
{
}
""",
        encoding="ascii",
    )


def main() -> None:
    args = parse_args()

    with h5py.File(args.input_cgns, "r") as f:
        zone = f["Base/Region"]
        points = read_points(zone)
        cells = read_cells(zone)
        patches = read_patches(zone)

    face_store: dict[tuple[int, ...], dict[str, object]] = {}
    duplicate_faces = 0

    for cell_id, cell in enumerate(cells):
        center = points[np.array(cell.nodes)].mean(axis=0)
        for raw_face in cell_faces(cell):
            oriented = orient_outward(points, raw_face, center)
            key = tuple(sorted(oriented))
            entry = face_store.get(key)
            if entry is None:
                face_store[key] = {
                    "face": oriented,
                    "owner": cell_id,
                    "neighbour": None,
                }
            elif entry["neighbour"] is None:
                first_owner = int(entry["owner"])
                if cell_id < first_owner:
                    entry["face"] = list(reversed(entry["face"]))
                    entry["owner"] = cell_id
                    entry["neighbour"] = first_owner
                else:
                    entry["neighbour"] = cell_id
            else:
                duplicate_faces += 1

    if duplicate_faces:
        raise ValueError(f"Encountered {duplicate_faces} non-manifold faces.")

    patch_lookup: dict[tuple[int, ...], tuple[str, str]] = {}
    patch_face_counter: Counter[str] = Counter()
    for patch in patches:
        for face in patch.faces:
            patch_lookup[tuple(sorted(face))] = (patch.name, patch.patch_type)
            patch_face_counter[patch.name] += 1

    internal_records: list[tuple[int, int, list[int]]] = []
    boundary_faces_by_patch: dict[str, list[tuple[list[int], int]]] = {patch.name: [] for patch in patches}
    boundary_patch_types = {patch.name: patch.patch_type for patch in patches}

    unassigned_boundary = 0
    for key, entry in face_store.items():
        face = list(entry["face"])
        owner = int(entry["owner"])
        neighbour = entry["neighbour"]
        if neighbour is None:
            patch_info = patch_lookup.get(key)
            if patch_info is None:
                unassigned_boundary += 1
                continue
            patch_name, _ = patch_info
            boundary_faces_by_patch[patch_name].append((face, owner))
        else:
            internal_records.append((owner, int(neighbour), face))

    if unassigned_boundary:
        raise ValueError(f"{unassigned_boundary} boundary faces were not found in ZoneBC patches.")

    internal_records.sort(key=lambda item: (item[0], item[1]))
    ordered_faces = [face for _, _, face in internal_records]
    ordered_owner = [owner for owner, _, _ in internal_records]
    ordered_neighbour = [neighbour for _, neighbour, _ in internal_records]
    boundary_entries: list[tuple[str, str, int, int]] = []

    start_face = len(ordered_faces)
    for patch in patches:
        patch_faces = boundary_faces_by_patch[patch.name]
        boundary_entries.append((patch.name, boundary_patch_types[patch.name], len(patch_faces), start_face))
        for face, owner in patch_faces:
            ordered_faces.append(face)
            ordered_owner.append(owner)
        start_face += len(patch_faces)

    poly_mesh = args.case_dir / "constant" / "polyMesh"
    poly_mesh.mkdir(parents=True, exist_ok=True)
    write_points(poly_mesh / "points", points)
    write_faces(poly_mesh / "faces", ordered_faces)
    write_label_list(poly_mesh / "owner", "owner", ordered_owner, "")
    write_label_list(poly_mesh / "neighbour", "neighbour", ordered_neighbour, "")
    write_boundary(poly_mesh / "boundary", boundary_entries)
    write_control_dict(args.case_dir)

    print(f"Wrote mesh to {args.case_dir}")
    print(f"Cells: {len(cells)}")
    print(f"Points: {len(points)}")
    print(f"Internal faces: {len(internal_records)}")
    print(f"Boundary faces: {len(ordered_faces) - len(internal_records)}")
    print(f"Patch counts: {dict((name, count) for name, _, count, _ in boundary_entries)}")


if __name__ == "__main__":
    main()
