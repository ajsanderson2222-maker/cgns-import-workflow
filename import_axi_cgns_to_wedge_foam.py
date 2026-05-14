#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np


@dataclass
class PatchInfo:
    name: str
    patch_type: str
    edges: list[tuple[int, int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a 2D axisymmetric STAR-style CGNS mesh into an OpenFOAM wedge case."
    )
    parser.add_argument("input_cgns", type=Path)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument(
        "--wedge-angle-deg",
        type=float,
        default=1.0,
        help="Total wedge angle in degrees.",
    )
    return parser.parse_args()


def decode_cgns_string(dataset: h5py.Dataset) -> str:
    data = dataset[()]
    if isinstance(data, bytes):
        return data.decode()
    if hasattr(data, "tobytes"):
        return data.tobytes().decode(errors="ignore").rstrip("\x00")
    return str(data)


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


def write_points(path: Path, points: list[tuple[float, float, float]]) -> None:
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


def write_label_list(path: Path, obj: str, values: list[int]) -> None:
    with path.open("w", encoding="ascii") as f:
        f.write(foam_header("labelList", obj))
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


def write_system_files(case_dir: Path) -> None:
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True, exist_ok=True)

    (system_dir / "controlDict").write_text(
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


def face_center(points: list[tuple[float, float, float]], face: list[int]) -> np.ndarray:
    return np.mean(np.array([points[i] for i in face], dtype=float), axis=0)


def face_normal(points: list[tuple[float, float, float]], face: list[int]) -> np.ndarray:
    coords = np.array([points[i] for i in face], dtype=float)
    origin = coords[0]
    normal = np.zeros(3)
    for i in range(1, len(coords) - 1):
        normal += np.cross(coords[i] - origin, coords[i + 1] - origin)
    return normal


def orient_face(points: list[tuple[float, float, float]], face: list[int], cell_center: np.ndarray) -> list[int]:
    center = face_center(points, face)
    normal = face_normal(points, face)
    if np.dot(normal, cell_center - center) > 0:
        return list(reversed(face))
    return face


def orient_side_face(
    points: list[tuple[float, float, float]],
    face: list[int],
    edge_a: tuple[float, float],
    edge_b: tuple[float, float],
    ccw: bool,
) -> list[int]:
    dx = edge_b[0] - edge_a[0]
    dr = edge_b[1] - edge_a[1]
    if ccw:
        outward_2d = np.array([dr, -dx, 0.0], dtype=float)
    else:
        outward_2d = np.array([-dr, dx, 0.0], dtype=float)
    normal = face_normal(points, face)
    if np.dot(normal, outward_2d) < 0:
        return list(reversed(face))
    return face


def rotate_point(x: float, r: float, angle_rad: float) -> tuple[float, float, float]:
    return (x, r * math.cos(angle_rad), r * math.sin(angle_rad))


def main() -> None:
    args = parse_args()
    half_angle = math.radians(args.wedge_angle_deg) / 2.0

    with h5py.File(args.input_cgns, "r") as f:
        zone = f["Base/Region"]

        x = zone["GridCoordinates"]["CoordinateX"][" data"][()]
        r = zone["GridCoordinates"]["CoordinateY"][" data"][()]
        z = zone["GridCoordinates"]["CoordinateZ"][" data"][()]

        if float(np.max(np.abs(z))) > 1e-12:
            raise ValueError("Expected an axisymmetric 2D mesh with all Z coordinates equal to zero.")

        region = zone["Region"]
        if int(region[" data"][()][0]) != 22:
            raise ValueError("Expected a polygonal 2D volume block (header 22).")

        conn = region["ElementConnectivity"][" data"][()]
        offsets = region["ElementStartOffset"][" data"][()]
        cells_2d = [tuple(int(v) - 1 for v in conn[int(s):int(e)]) for s, e in zip(offsets[:-1], offsets[1:])]

        patches: list[PatchInfo] = []
        axis_points: set[int] = set()
        edge_to_patch: dict[tuple[int, int], tuple[str, str]] = {}

        for patch_name in zone["ZoneBC"]:
            bc = zone["ZoneBC"][patch_name]
            elem_group = zone[patch_name]
            header = int(elem_group[" data"][()][0])
            if header != 3:
                raise ValueError(f"Expected BAR_2 edge block for patch {patch_name}, got header {header}.")

            raw_conn = elem_group["ElementConnectivity"][" data"][()]
            if len(raw_conn) % 2:
                raise ValueError(f"Odd edge connectivity length for patch {patch_name}.")

            edges = []
            for i in range(0, len(raw_conn), 2):
                a = int(raw_conn[i]) - 1
                b = int(raw_conn[i + 1]) - 1
                edge = (a, b)
                edges.append(edge)

            bc_type = decode_cgns_string(bc[" data"])
            clean_name = patch_name.split(".")[-1].lower().replace("-", "_")
            foam_type = "patch"
            if "AXIS" in patch_name.upper() or bc_type == "Null":
                clean_name = "axis"
                foam_type = "empty"
                for a, b in edges:
                    axis_points.add(a)
                    axis_points.add(b)
            elif bc_type == "BCWall":
                foam_type = "wall"

            patches.append(PatchInfo(name=clean_name, patch_type=foam_type, edges=edges))
            for a, b in edges:
                edge_to_patch[tuple(sorted((a, b)))] = (clean_name, foam_type)

    points_3d: list[tuple[float, float, float]] = []
    front_idx: dict[int, int] = {}
    back_idx: dict[int, int] = {}

    for i, (xp, rp) in enumerate(zip(x, r)):
        if i in axis_points or abs(float(rp)) < 1e-12:
            idx = len(points_3d)
            points_3d.append((float(xp), 0.0, 0.0))
            front_idx[i] = idx
            back_idx[i] = idx
        else:
            idx_front = len(points_3d)
            points_3d.append(rotate_point(float(xp), float(rp), -half_angle))
            idx_back = len(points_3d)
            points_3d.append(rotate_point(float(xp), float(rp), half_angle))
            front_idx[i] = idx_front
            back_idx[i] = idx_back

    def front_face(cell: tuple[int, ...]) -> list[int]:
        return [front_idx[n] for n in cell]

    def back_face(cell: tuple[int, ...]) -> list[int]:
        return [back_idx[n] for n in reversed(cell)]

    def side_face(a: int, b: int) -> list[int]:
        af = front_idx[a]
        ab = back_idx[a]
        bf = front_idx[b]
        bb = back_idx[b]

        a_axis = af == ab
        b_axis = bf == bb

        if a_axis and b_axis:
            return [af, bf, bb, ab]
        if a_axis:
            return [af, bf, bb]
        if b_axis:
            return [af, bf, ab]
        return [af, bf, bb, ab]

    edge_store: dict[tuple[int, int], dict[str, object]] = {}
    front_patch: list[tuple[list[int], int]] = []
    back_patch: list[tuple[list[int], int]] = []
    boundary_faces_by_patch: dict[str, list[tuple[list[int], int]]] = {p.name: [] for p in patches}

    for cell_id, cell in enumerate(cells_2d):
        coords2d = np.array([(float(x[n]), float(r[n])) for n in cell], dtype=float)
        center2d = np.mean(coords2d, axis=0)
        cell_center = np.array(rotate_point(float(center2d[0]), float(center2d[1]), 0.0), dtype=float)
        area2 = 0.0
        for i in range(len(cell)):
            x0, y0 = coords2d[i]
            x1, y1 = coords2d[(i + 1) % len(cell)]
            area2 += x0 * y1 - x1 * y0
        ccw = area2 > 0.0

        ff = orient_face(points_3d, front_face(cell), cell_center)
        bf = orient_face(points_3d, back_face(cell), cell_center)
        front_patch.append((ff, cell_id))
        back_patch.append((bf, cell_id))

        n = len(cell)
        for i in range(n):
            a = cell[i]
            b = cell[(i + 1) % n]
            key = tuple(sorted((a, b)))
            patch_info = edge_to_patch.get(key)
            if patch_info is not None and patch_info[0] == "axis":
                continue
            face = orient_side_face(
                points_3d,
                side_face(a, b),
                (float(x[a]), float(r[a])),
                (float(x[b]), float(r[b])),
                ccw,
            )
            entry = edge_store.get(key)
            if entry is None:
                edge_store[key] = {"face": face, "owner": cell_id, "neighbour": None}
            elif entry["neighbour"] is None:
                first_owner = int(entry["owner"])
                if cell_id < first_owner:
                    entry["face"] = face
                    entry["owner"] = cell_id
                    entry["neighbour"] = first_owner
                else:
                    entry["neighbour"] = cell_id
            else:
                raise ValueError(f"Non-manifold edge detected for edge {key}.")

    internal_records: list[tuple[int, int, list[int]]] = []
    for key, entry in edge_store.items():
        face = list(entry["face"])
        owner = int(entry["owner"])
        neighbour = entry["neighbour"]
        if neighbour is None:
            patch_info = edge_to_patch.get(key)
            if patch_info is None:
                raise ValueError(f"Boundary edge {key} was not found in any patch block.")
            patch_name, _ = patch_info
            boundary_faces_by_patch[patch_name].append((face, owner))
        else:
            internal_records.append((owner, int(neighbour), face))

    internal_records.sort(key=lambda item: (item[0], item[1]))
    faces = [face for _, _, face in internal_records]
    owner = [a for a, _, _ in internal_records]
    neighbour = [b for _, b, _ in internal_records]

    patch_entries: list[tuple[str, str, int, int]] = []
    start_face = len(faces)

    for patch in patches:
        patch_faces = boundary_faces_by_patch[patch.name]
        patch_entries.append((patch.name, patch.patch_type, len(patch_faces), start_face))
        for face, cell_owner in patch_faces:
            faces.append(face)
            owner.append(cell_owner)
        start_face += len(patch_faces)

    patch_entries.append(("wedge_front", "wedge", len(front_patch), start_face))
    for face, cell_owner in front_patch:
        faces.append(face)
        owner.append(cell_owner)
    start_face += len(front_patch)

    patch_entries.append(("wedge_back", "wedge", len(back_patch), start_face))
    for face, cell_owner in back_patch:
        faces.append(face)
        owner.append(cell_owner)
    start_face += len(back_patch)

    poly_mesh = args.case_dir / "constant" / "polyMesh"
    poly_mesh.mkdir(parents=True, exist_ok=True)

    write_points(poly_mesh / "points", points_3d)
    write_faces(poly_mesh / "faces", faces)
    write_label_list(poly_mesh / "owner", "owner", owner)
    write_label_list(poly_mesh / "neighbour", "neighbour", neighbour)
    write_boundary(poly_mesh / "boundary", patch_entries)
    write_system_files(args.case_dir)

    print(f"Wrote mesh to {args.case_dir}")
    print(f"2D cells: {len(cells_2d)}")
    print(f"3D points: {len(points_3d)}")
    print(f"Internal faces: {len(internal_records)}")
    print(f"Boundary patches: {[name for name, _, _, _ in patch_entries]}")


if __name__ == "__main__":
    main()
