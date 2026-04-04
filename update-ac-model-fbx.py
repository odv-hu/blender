import bpy
import re

# Current version is generated with ChatGPT! 

# =========================================================
# USER SETTINGS
# =========================================================
FBX_PATH = r"FILEPATH"  # <-- THIS IS THE FILE PATH. TODO: CREATE A UI POPUP TO BROWSE FOR IT
TARGET_COLLECTION_NAME = "ARCHICAD MODEL"               # <-- THIS IS THE COLLECTION WHICH CONTAINS THE ARCHICAD MODEL TO-BE-UPDATED
TEMP_COLLECTION_NAME = "__TEMP_FBX__"                   # <-- THIS COLLECTION SHOULD NEVER BE RENDERED, IT HOSTS THE IMPORTED MODEL TERMPORARILY.

# =========================================================
# HELPER FUNCTIONS
# =========================================================
blender_dup_suffix_re = re.compile(r"^(.*)\.(\d{3})$")


def canonical_name(name: str) -> str:
    """
    Canonical name is a weird way to say the original Archicad surface name without any Blender suffices.
    Strip Blender duplicate suffix: MaterialName.001 -> MaterialName (this happens during the import to the temporary collection)
    """
    m = blender_dup_suffix_re.match(name)
    if m:
        return m.group(1)
    return name


def get_or_create_collection(name: str):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def purge_collection_objects(col):
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def import_fbx(filepath: str):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=filepath)
    after = set(bpy.data.objects)
    return list(after - before)


def move_object_exclusively_to_collection(obj, target_col):
    # Link to target if needed
    if obj not in target_col.objects[:]:
        target_col.objects.link(obj)

    # Unlink from every other collection
    for col in list(obj.users_collection):
        if col != target_col:
            col.objects.unlink(obj)


def build_existing_map(target_col):
    """
    Existing objects are keyed by their actual name.
    Assumes that the scene-side names are the reference (Archicad Surface attribute) names.
    """
    result = {}
    for obj in target_col.objects:
        if obj.type != 'MESH':
            continue
        result[obj.name] = obj
    return result


def build_imported_map(imported_objects, existing_map):
    """
    Build a map from canonical imported name to imported object.

    Example:
      imported Air.001 -> canonical Air
      if Air exists in target, match to Air

    If canonical name doesn't exist in target, the canonical name is still used.
    """
    result = {}
    for obj in imported_objects:
        if obj.type != 'MESH':
            continue

        key = canonical_name(obj.name)

        # If there are collisions, keep first and warn
        if key in result:
            print(f"WARNING: duplicate imported canonical name: {key} "
                  f"({result[key].name} and {obj.name})")
            continue

        result[key] = obj
    return result


def preserve_existing_materials(existing_obj):
    return [slot.material for slot in existing_obj.material_slots]


def apply_materials_to_mesh(obj, materials):
    obj.data.materials.clear()
    for mat in materials:
        obj.data.materials.append(mat)


def remap_materials_by_name(obj):
    """
    For newly added objects:
    if imported material is Wood.001 and Wood exists, replace with Wood.
    """
    for i, slot in enumerate(obj.material_slots):
        mat = slot.material
        if mat is None:
            continue

        key = canonical_name(mat.name)
        existing = bpy.data.materials.get(key)
        if existing is not None:
            obj.material_slots[i].material = existing


def copy_uvs_if_same_topology(src_mesh, dst_mesh):
    """
    Copy UV layers from src_mesh to dst_mesh if topology matches. <-- TODO: research needed, this does not seem to work. 
    Custom UV maps are lost, procedural texture mapping is advised. 
    """
    if src_mesh is None or dst_mesh is None:
        return False

    if (
        len(src_mesh.vertices) != len(dst_mesh.vertices) or
        len(src_mesh.loops) != len(dst_mesh.loops) or
        len(src_mesh.polygons) != len(dst_mesh.polygons)
    ):
        return False

    while dst_mesh.uv_layers:
        dst_mesh.uv_layers.remove(dst_mesh.uv_layers[0])

    for src_layer in src_mesh.uv_layers:
        dst_layer = dst_mesh.uv_layers.new(name=src_layer.name, do_init=False)
        for i, src_data in enumerate(src_layer.data):
            dst_layer.data[i].uv = src_data.uv

    try:
        if src_mesh.uv_layers.active:
            active_name = src_mesh.uv_layers.active.name
            if active_name in dst_mesh.uv_layers:
                dst_mesh.uv_layers.active = dst_mesh.uv_layers[active_name]
    except Exception:
        pass

    return True


def replace_geometry(existing_obj, imported_obj, preserve_uvs=True):
    """
    Replace existing object's mesh with imported mesh.
    Keep existing materials.
    Optionally copy UVs from old mesh if topology matches. <-- TODO: research needed, this does not seem to work. 
    """
    old_mesh = existing_obj.data
    new_mesh = imported_obj.data

    existing_materials = preserve_existing_materials(existing_obj)

    if preserve_uvs:
        copy_uvs_if_same_topology(old_mesh, new_mesh)

    existing_obj.data = new_mesh
    apply_materials_to_mesh(existing_obj, existing_materials)

    # Remove imported object shell
    bpy.data.objects.remove(imported_obj, do_unlink=True)

    # Remove old mesh if unused
    if old_mesh and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def clear_geometry(obj):
    old_mesh = obj.data
    empty_mesh = bpy.data.meshes.new(f"{obj.name}_EMPTY")
    obj.data = empty_mesh

    # Optional: keeping material slots for visual consistency in the outliner/data:
    # apply_materials_to_mesh(obj, [slot.material for slot in obj.material_slots])

    if old_mesh and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


# =========================================================
# MAIN
# =========================================================
target_col = get_or_create_collection(TARGET_COLLECTION_NAME)
temp_col = get_or_create_collection(TEMP_COLLECTION_NAME)

# Clean temp collection from previous failed runs
purge_collection_objects(temp_col)

# Import FBX file
imported_objects = import_fbx(FBX_PATH)

# Move imported objects exclusively into temp collection
for obj in imported_objects:
    move_object_exclusively_to_collection(obj, temp_col)

existing_map = build_existing_map(target_col)
imported_map = build_imported_map(imported_objects, existing_map)

existing_names = set(existing_map.keys())
imported_names = set(imported_map.keys())

matched = existing_names & imported_names
new = imported_names - existing_names
missing = existing_names - imported_names

print("Matched:", sorted(matched))
print("New:", sorted(new))
print("Missing:", sorted(missing))

# ---------------------------------------------------------
# 1. Existing name -> update geometry, keep materials
# ---------------------------------------------------------
for name in matched:
    replace_geometry(existing_map[name], imported_map[name], preserve_uvs=True)

# ---------------------------------------------------------
# 2. New name -> add object, remap materials by name
# ---------------------------------------------------------
for name in new:
    obj = imported_map[name]

    remap_materials_by_name(obj)

    # Rename imported object to canonical name before moving in
    obj.name = name
    if obj.data:
        obj.data.name = name

    move_object_exclusively_to_collection(obj, target_col)

# ---------------------------------------------------------
# 3. Missing from new FBX -> keep object, clear geometry
# ---------------------------------------------------------
for name in missing:
    clear_geometry(existing_map[name])

# ---------------------------------------------------------
# Cleanup temp collection leftovers
# ---------------------------------------------------------
purge_collection_objects(temp_col)

print(
    f"DONE | updated={len(matched)} | new={len(new)} | cleared={len(missing)}"
)