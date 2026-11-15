"""Headless test of the Archicad FBX Updater: matching by surface (#37) and
material slots kept on update (#38), on synthetic FBX files.

Unpack the built extension into a folder named odv_tools, then run either

    blender --factory-startup -b --python tests/test_fbx_model_update.py -- <parent of odv_tools> <output folder>
    python3 tests/test_fbx_model_update.py -- <parent of odv_tools> <output folder>   (bpy module)

It exports small FBX files of cube "elements" into the output folder and updates
a target collection from them, with objects of the same surface names already in
another collection, as in a file with an older copy of the model. It checks:
suffixed objects keep being updated in place (no new copy per update); objects
from earlier versions (no stored surface, `.00n` name, emptied duplicates); the
surfaces reported as present outside the target; faces assigned to a second slot
in Blender keep it while they do not move; an emptied object keeps its materials
and gets them back when its surface returns; the same with *Merge by distance*.
It never opens or saves a .blend. Exit code 1 if a check fails.
Not covered: a real Archicad FBX, the panel warning, the operator's reports.
"""
import os
import sys

import bpy
import bmesh  # noqa: E402  (after bpy: the bpy module provides it)

args = sys.argv[sys.argv.index("--") + 1:]
PKG_PARENT, OUT = args[0], args[1]
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, PKG_PARENT)

bpy.ops.wm.read_factory_settings(use_empty=True)
import odv_tools  # noqa: E402
from odv_tools.archicad import fbx_model_update as fu  # noqa: E402

odv_tools.register()

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def material(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def cube(name, loc, mat_name, coll):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(loc[0] + 0.5, loc[1] + 0.5, loc[2] + 0.5))
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material(mat_name))
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
    return obj


def export_fbx(tag, elements):
    """elements: [(name, (x, y, z), surface)] -> path of the FBX."""
    src = bpy.data.scenes.new("FBXSRC")
    for name, loc, surface in elements:
        cube(f"{tag}_{name}", loc, surface, src.collection)
    path = os.path.join(OUT, f"{tag}.fbx")
    with bpy.context.temp_override(scene=src, view_layer=src.view_layers[0]):
        bpy.ops.export_scene.fbx(filepath=path, use_selection=False, object_types={'MESH'})
    for obj in list(src.collection.objects):
        me = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(me)
    bpy.data.scenes.remove(src)
    return path


V1 = [("wall1", (0, 0, 0), "Paint"), ("wall2", (3, 0, 0), "Paint"),
      ("glass", (6, 0, 0), "Glass"), ("brick", (9, 0, 0), "Brick")]
V2 = [("wall1", (0, 0, 0), "Paint"), ("wall2", (3, 0, 1), "Paint"),   # wall2 moved up 1 m
      ("brick", (9, 0, 0), "Brick")]                                     # glass gone
fbx_v1 = export_fbx("v1", V1)
fbx_v2 = export_fbx("v2", V2)

scene = bpy.context.scene
scene.ac_target_collection = "MODEL"

# an older copy of the model in another collection holds the plain names
old_copy = bpy.data.collections.new("MODEL-OLD")
scene.collection.children.link(old_copy)
cube("Paint", (0, 5, 0), "Paint", old_copy)
cube("Brick", (9, 5, 0), "Brick", old_copy)


def update(path, merge=False):
    scene.ac_fbx_path = path
    scene.ac_merge_by_distance = merge
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        return bpy.ops.odv.ac_update_from_fbx()


def model():
    return bpy.data.collections["MODEL"]


def by_surface(surface):
    found = [o for o in model().objects if o.get(fu.SURFACE_KEY) == surface]
    return found[0] if len(found) == 1 else None


def tops_in_slot(obj, slot, x_range):
    """Faces facing up at the top of the element between x_range: how many in `slot`, how many in all."""
    faces = [p for p in obj.data.polygons
             if p.normal.z > 0.99 and x_range[0] < p.center.x < x_range[1]]
    return sum(1 for p in faces if p.material_index == slot), len(faces)


def other_faces_slot0(obj, exclude):
    return all(p.material_index == 0 for p in obj.data.polygons if p.index not in exclude)


# --- 1. first update: target missing, plain names taken elsewhere ------------
r = update(fbx_v1)
check("update 1 ran", r == {'FINISHED'})
paint, glass, brick = by_surface("Paint"), by_surface("Glass"), by_surface("Brick")
check("update 1: one object per surface, with the stored surface",
      None not in (paint, glass, brick), str([(o.name, o.get(fu.SURFACE_KEY)) for o in model().objects]))
check("update 1: Paint and Brick suffixed (names taken), Glass plain",
      paint.name == "Paint.001" and brick.name == "Brick.001" and glass.name == "Glass",
      f"{paint.name}, {brick.name}, {glass.name}")
temp = bpy.data.collections[scene.ac_temp_collection]
outside = fu.surfaces_outside({"Paint", "Glass", "Brick"}, model(), temp)
check("surfaces outside the target reported", outside == {"Paint": "MODEL-OLD", "Brick": "MODEL-OLD"}, str(outside))

# material work in Blender on the suffixed object
plywood, plaster = material("Plywood"), material("Plaster")
paint.data.materials[0] = plywood
paint.data.materials.append(plaster)
for p in paint.data.polygons:
    if p.normal.z > 0.99:
        p.material_index = 1        # both tops plaster
paint.pass_index = 42
paint["note"] = "kept"
paint.modifiers.new("Bevel", 'BEVEL')
glass.data.materials[0] = material("GlassBlender")
paint_ptr = paint.as_pointer()

# objects from an earlier version: no stored surface, suffixed, an emptied duplicate
del brick[fu.SURFACE_KEY]
brick.name = "Brick.003"
dup = bpy.data.objects.new("Brick.002", bpy.data.meshes.new("Brick.002_EMPTY"))
model().objects.link(dup)
n_before = len(model().objects)

# --- 2. same FBX again ----------------------------------------------------------
r = update(fbx_v1)
check("update 2 ran", r == {'FINISHED'})
check("update 2: no objects added", len(model().objects) == n_before,
      f"{n_before} -> {len(model().objects)}: {sorted(o.name for o in model().objects)}")
paint = bpy.data.objects.get("Paint.001")
check("update 2: the suffixed object updated in place", paint is not None and paint.as_pointer() == paint_ptr
      and len(paint.data.polygons) > 0)
check("update 2: Plywood and Plaster slots kept", [m.name for m in paint.data.materials] == ["Plywood", "Plaster"],
      str([m.name for m in paint.data.materials]))
check("update 2: pass index, custom property, modifier kept",
      paint.pass_index == 42 and paint.get("note") == "kept" and len(paint.modifiers) == 1)
t1, t2 = tops_in_slot(paint, 1, (0, 1)), tops_in_slot(paint, 1, (3, 4))
check("update 2: both tops still in the Plaster slot", t1[0] == t1[1] > 0 and t2[0] == t2[1] > 0, f"{t1}, {t2}")
tops = {p.index for p in paint.data.polygons if p.normal.z > 0.99}
check("update 2: all other faces in the first slot", other_faces_slot0(paint, tops))
brick = bpy.data.objects.get("Brick.003")
check("update 2: earlier-version object matched by its name without suffix",
      brick is not None and len(brick.data.polygons) > 0 and brick.get(fu.SURFACE_KEY) == "Brick")
check("update 2: emptied duplicate left empty", len(bpy.data.objects["Brick.002"].data.polygons) == 0)
check("update 2: old copy untouched", len(bpy.data.objects["Paint"].data.polygons) == 6
      and bpy.data.objects["Paint"].data.materials[0].name == "Paint")

# --- 3. wall2 moved, glass gone ----------------------------------------------
r = update(fbx_v2)
check("update 3 ran", r == {'FINISHED'})
t1, t2 = tops_in_slot(paint, 1, (0, 1)), tops_in_slot(paint, 1, (3, 4))
check("update 3: unmoved top keeps Plaster", t1[0] == t1[1] > 0, str(t1))
check("update 3: moved element back in the first slot", t2[0] == 0 and t2[1] > 0, str(t2))
glass = bpy.data.objects.get("Glass")
check("update 3: missing surface emptied", glass is not None and len(glass.data.polygons) == 0)
check("update 3: emptied object keeps its material", [m.name for m in glass.data.materials] == ["GlassBlender"],
      str([m.name for m in glass.data.materials]))
empty_mesh = glass.data.name
update(fbx_v2)
check("update 3b: an empty object is not emptied again", glass.data.name == empty_mesh)

# --- 4. back to v1, with Merge by distance -------------------------------------
r = update(fbx_v1, merge=True)
check("update 4 ran", r == {'FINISHED'})
check("update 4: returning surface back in the same object with its material",
      bpy.data.objects.get("Glass") is glass and len(glass.data.polygons) > 0
      and [m.name for m in glass.data.materials] == ["GlassBlender"])
t1 = tops_in_slot(paint, 1, (0, 1))
check("update 4 (merge): unmoved top keeps Plaster", t1[0] == t1[1] > 0, str(t1))
check("update 4 (merge): welded", len(paint.data.vertices) == 16, str(len(paint.data.vertices)))
check("no .001 materials left", not any(fu.DUP_SUFFIX.match(m.name) for m in bpy.data.materials),
      str([m.name for m in bpy.data.materials]))
check("temp collection empty", len(temp.objects) == 0)
check("no new copies over four updates", len(model().objects) == n_before, str(len(model().objects)))

odv_tools.unregister()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)} of {len(results)} checks passed")
sys.exit(1 if failed else 0)
