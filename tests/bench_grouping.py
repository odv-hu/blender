"""Compare and time the grouping step of the Archicad FBX Updater (#16): the
operator version (join, apply transform, separate by material) of odv tools 0.0.7
against the mesh-data version, on the same synthetic import.

    python3 tests/bench_grouping.py -- <parent of odv_tools> <old module.py> [elements] [fbx folder or -] [materials]

<old module.py> is archicad/fbx_model_update/__init__.py of 0.0.7, e.g.
`git show v0.0.7:archicad/fbx_model_update/__init__.py > old.py`. With a folder,
the synthetic elements go through an FBX export and import first, as from
Archicad. Each element is a box with six faces of three materials, rotated,
scaled and with a UV map and custom normals; one in ten has a face without a
material. Per material, the two results must have the same faces, matched by their
centres: corner positions (within 0.1 mm), UVs and corner normals (within 0.01:
the two round the transformed positions differently in the last bits). Prints the times.
Not part of the extension.
"""
import importlib.util
import math
import os
import sys
import time

import bpy
import bmesh
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, args[0])
N = int(args[2]) if len(args) > 2 else 300
FBX_DIR = args[3] if len(args) > 3 and args[3] != "-" else None
M = int(args[4]) if len(args) > 4 else 3

bpy.ops.wm.read_factory_settings(use_empty=True)
import odv_tools  # noqa: E402
from odv_tools.archicad import fbx_model_update as new  # noqa: E402

spec = importlib.util.spec_from_file_location("old_fu", args[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

MATS = []


def element(i, coll):
    me = bpy.data.meshes.new(f"el{i}")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for k, loop in enumerate(f.loops):
            loop[uv].uv = ((i % 7) * 0.1 + k * 0.25, (i % 5) * 0.1 + k * 0.125)
    bm.to_mesh(me)
    bm.free()
    for m in MATS:
        me.materials.append(m)
    mi = [(i + j) % M for j in range(6)] if M > 3 else [j % 3 for j in range(6)]
    me.polygons.foreach_set("material_index", mi)
    if i % 10 == 0:
        me.materials.append(None)
        me.polygons[5].material_index = M
    me.normals_split_custom_set([(0.3 * math.sin(i + k), 0.2, 1.0) for k in range(len(me.loops))])
    ob = bpy.data.objects.new(f"el{i}", me)
    ob.location = (i % 20 * 1.5, i // 20 * 1.5, (i % 3) * 0.7)
    ob.rotation_euler = (0.1 * (i % 4), 0.2 * (i % 3), 0.3 * (i % 5))
    ob.scale = (1.0 + 0.1 * (i % 3),) * 3
    coll.objects.link(ob)
    return ob


def make(name):
    # a fresh file for each version, so neither pays for the other's leftovers
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MATS[:] = [bpy.data.materials.new(n) for n in ("Wall", "Plaster", "Glass")[:M]] + \
        [bpy.data.materials.new(f"Surface{k:02d}") for k in range(M - 3)]
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    obs = [element(i, coll) for i in range(N)]
    if FBX_DIR:
        os.makedirs(FBX_DIR, exist_ok=True)
        path = os.path.join(FBX_DIR, f"{name}.fbx")
        bpy.ops.object.select_all(action='DESELECT')
        for o in obs:
            o.select_set(True)
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, mesh_smooth_type='FACE')
        for o in obs:
            bpy.data.objects.remove(o)
        obs = new.import_fbx(path)
        for o in obs:
            new.move_exclusively(o, coll)
        new.dedupe_materials(obs)
    return coll, obs


def signature(obj):
    """Faces as arrays of corners (x, y, z, u, v, nx, ny, nz)."""
    me = obj.data
    m = np.array(obj.matrix_world)
    co = np.array([v.co[:] for v in me.vertices]) @ m[:3, :3].T + m[:3, 3]
    uv = me.uv_layers.active.data if me.uv_layers.active else None
    cn = me.corner_normals
    faces = []
    for p in me.polygons:
        corners = [list(co[me.loops[li].vertex_index]) + (list(uv[li].uv) if uv else [])
                   + list(cn[li].vector) for li in p.loop_indices]
        faces.append(np.array(corners))
    return faces


def same_faces(fa, fb):
    """Each face of fa has a face in fb at the same place (nearest centre within
    0.1 mm) with the same corners, starting from the corner nearest fa's first."""
    if len(fa) != len(fb):
        return False
    if not fa:
        return True
    cb = np.array([f[:, :3].mean(0) for f in fb])
    used = set()
    for a in fa:
        d = np.linalg.norm(cb - a[:, :3].mean(0), axis=1)
        j = int(d.argmin())
        b = fb[j]
        if d[j] > 1e-4 or j in used or a.shape != b.shape:
            return False
        used.add(j)
        k = int(np.linalg.norm(b[:, :3] - a[0, :3], axis=1).argmin())
        b = np.roll(b, -k, axis=0)
        if not np.allclose(a[:, :-3], b[:, :-3], atol=1e-4) or not np.allclose(a[:, -3:], b[:, -3:], atol=0.01):
            return False
    return True


results = {}
for label, mod in (("operators (0.0.7)", old), ("mesh data", new)):
    coll, obs = make(label)
    temp = bpy.data.collections.new(label + " temp")
    bpy.context.scene.collection.children.link(temp)
    for o in obs:
        new.move_exclusively(o, temp)
    nf = sum(len(o.data.polygons) for o in obs)
    t = time.perf_counter()
    out = mod.bucket_by_material(obs, temp)
    dt = time.perf_counter() - t
    results[label] = {k: signature(v) for k, v in out.items()}
    print(f"{label:18} {len(obs)} objects, {nf} faces -> {sorted(out)}: {dt:.2f} s")

a, b = results.values()
same = a.keys() == b.keys() and all(same_faces(a[k], b[k]) for k in a)
print("same faces, positions, UVs and corner normals per material:", same)
if not same:
    for k in a:
        if not same_faces(a.get(k, []), b.get(k, [])):
            print("  differs:", k, len(a.get(k, [])), len(b.get(k, [])))
sys.exit(0 if same else 1)
