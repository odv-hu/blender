"""Archicad FBX Updater: update an Archicad model in the scene from a new FBX export.

Groups the import by surface (material) and keeps the Blender-side materials,
pass indices, modifiers and custom properties of existing objects.
"""

import re
import bpy
from mathutils import Matrix


DUP_SUFFIX = re.compile(r"^(.*)\.(\d{3})$")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def canonical(name):
    """Felulet-feher.001 -> Felulet-feher"""
    m = DUP_SUFFIX.match(name)
    return m.group(1) if m else name


def get_or_create_collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if col.name not in {c.name for c in parent.children}:
        try:
            parent.children.link(col)
        except RuntimeError:
            pass
    return col


def purge_collection(col):
    for obj in list(col.objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)


def move_exclusively(obj, target):
    if obj.name not in target.objects:
        target.objects.link(obj)
    for col in list(obj.users_collection):
        if col != target:
            col.objects.unlink(obj)


def import_fbx(filepath):
    """Returns the objects the import created. Handles both importers."""
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "fbx_import"):
        try:
            bpy.ops.wm.fbx_import(filepath=filepath)
        except (RuntimeError, TypeError):
            bpy.ops.import_scene.fbx(filepath=filepath)
    else:
        bpy.ops.import_scene.fbx(filepath=filepath)
    return [o for o in set(bpy.data.objects) - before]


def dedupe_materials(objects):
    """Point every slot at the canonical material, so Wood.001 -> Wood."""
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            if slot.material is None:
                continue
            base = canonical(slot.material.name)
            if base == slot.material.name:
                continue
            existing = bpy.data.materials.get(base)
            if existing is not None:
                slot.material = existing


def purge_orphan_dupe_materials():
    for mat in list(bpy.data.materials):
        if mat.users == 0 and DUP_SUFFIX.match(mat.name):
            bpy.data.materials.remove(mat)


def activate(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# ---------------------------------------------------------------------------
# the transform: element-structured input -> surface-structured scene
# ---------------------------------------------------------------------------

def bucket_by_material(objects, temp_col):
    """Join everything, split by material, one object per surface.

    Returns {material_name: object}. No name parsing involved -- the grouping
    key is the material index on each polygon, which is what Archicad's
    surface assignment actually became on export.
    """
    meshes = [o for o in objects if o.type == 'MESH' and o.data and len(o.data.polygons)]
    if not meshes:
        return {}

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # 1. one mega mesh (join bakes each object's world transform in)
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    merged = bpy.context.view_layer.objects.active

    # 2. flatten the transform so nothing can drift between updates
    activate(merged)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # 3. split it back out, one object per material
    activate(merged)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.separate(type='MATERIAL')
    bpy.ops.object.mode_set(mode='OBJECT')

    pieces = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    if merged not in pieces:
        pieces.append(merged)

    result = {}
    for obj in pieces:
        move_exclusively(obj, temp_col)
        activate(obj)
        try:
            bpy.ops.object.material_slot_remove_unused()
        except RuntimeError:
            pass

        if not obj.data.materials or obj.data.materials[0] is None:
            bpy.data.objects.remove(obj, do_unlink=True)
            continue

        name = obj.data.materials[0].name
        if name in result:
            # shouldn't happen after separate-by-material, but never drop geometry
            bpy.ops.object.select_all(action='DESELECT')
            result[name].select_set(True)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = result[name]
            bpy.ops.object.join()
            continue

        obj.name = name
        obj.data.name = name
        obj.matrix_world = Matrix.Identity(4)
        result[name] = obj

    return result


# ---------------------------------------------------------------------------
# update steps
# ---------------------------------------------------------------------------

def swap_geometry(existing, incoming):
    """Keep the object shell -- pass_index, modifiers, custom props all survive."""
    old_mesh = existing.data
    kept = [s.material for s in existing.material_slots]

    existing.data = incoming.data
    existing.matrix_world = Matrix.Identity(4)

    existing.data.materials.clear()
    for mat in kept:
        existing.data.materials.append(mat)

    bpy.data.objects.remove(incoming, do_unlink=True)
    if old_mesh and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def clear_geometry(obj):
    old = obj.data
    obj.data = bpy.data.meshes.new(f"{obj.name}_EMPTY")
    if old and old.users == 0:
        bpy.data.meshes.remove(old)


def next_free_pass_index(collection):
    used = {o.pass_index for o in collection.objects}
    i = 1
    while i in used:
        i += 1
    return i


# ---------------------------------------------------------------------------
# operator
# ---------------------------------------------------------------------------

class ODV_OT_ac_update_from_fbx(bpy.types.Operator):
    bl_idname = "odv.ac_update_from_fbx"
    bl_label = "Update model from FBX"
    bl_description = ("Import the FBX and update the objects in the target collection, "
                      "keeping their materials, pass indices, modifiers and custom properties")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.scene.ac_fbx_path:
            cls.poll_message_set("Select an FBX file first")
            return False
        return True

    def execute(self, context):
        s = context.scene
        path = bpy.path.abspath(s.ac_fbx_path)
        if not path:
            self.report({'ERROR'}, "No FBX file selected")
            return {'CANCELLED'}

        target = get_or_create_collection(s.ac_target_collection)
        temp = get_or_create_collection(s.ac_temp_collection)
        purge_collection(temp)

        imported = import_fbx(path)
        for obj in imported:
            move_exclusively(obj, temp)

        dedupe_materials(imported)
        incoming = bucket_by_material(imported, temp)

        existing = {o.name: o for o in target.objects if o.type == 'MESH'}

        matched = set(existing) & set(incoming)
        added = set(incoming) - set(existing)
        gone = set(existing) - set(incoming)

        for name in matched:
            swap_geometry(existing[name], incoming[name])

        for name in added:
            obj = incoming[name]
            move_exclusively(obj, target)
            if s.ac_autoindex:
                obj.pass_index = next_free_pass_index(target)

        if s.ac_clear_missing:
            for name in gone:
                clear_geometry(existing[name])

        purge_collection(temp)
        purge_orphan_dupe_materials()

        self.report(
            {'INFO'},
            f"updated {len(matched)} | new {len(added)} | missing {len(gone)}"
        )
        print(f"[AC Updater] matched: {sorted(matched)}")
        print(f"[AC Updater] new:     {sorted(added)}")
        print(f"[AC Updater] missing: {sorted(gone)}")
        return {'FINISHED'}


class ODV_OT_ac_reindex(bpy.types.Operator):
    bl_idname = "odv.ac_reindex"
    bl_label = "Assign pass indices"
    bl_description = "Give every object in the target collection a unique pass index"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        target = bpy.data.collections.get(context.scene.ac_target_collection)
        if target is None:
            self.report({'ERROR'}, "Target collection not found")
            return {'CANCELLED'}
        for i, obj in enumerate(sorted(target.objects, key=lambda o: o.name), start=1):
            obj.pass_index = i
            for mat in obj.data.materials:
                if mat:
                    mat.pass_index = i
        self.report({'INFO'}, f"indexed {len(target.objects)} objects")
        return {'FINISHED'}


class ODV_PT_ac_fbx_updater(bpy.types.Panel):
    bl_label = "Archicad FBX Updater"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "odv"

    def draw(self, context):
        s = context.scene
        layout = self.layout
        layout.prop(s, "ac_fbx_path")

        box = layout.box()
        box.label(text="Options")
        box.prop(s, "ac_clear_missing")
        box.prop(s, "ac_autoindex")

        col = layout.column()
        col.operator("odv.ac_update_from_fbx", icon='FILE_REFRESH')
        col.operator("odv.ac_reindex", icon='MATERIAL')


class ODV_PT_ac_fbx_updater_collections(bpy.types.Panel):
    """The collections the updater works with; rarely changed, so closed by default."""
    bl_label = "Collections"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "odv"
    bl_parent_id = "ODV_PT_ac_fbx_updater"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene
        col = self.layout.column()
        col.prop(s, "ac_target_collection")
        col.prop(s, "ac_temp_collection")


# ---------------------------------------------------------------------------

classes = (
    ODV_OT_ac_update_from_fbx,
    ODV_OT_ac_reindex,
    ODV_PT_ac_fbx_updater,
    ODV_PT_ac_fbx_updater_collections,
)


def register():
    bpy.types.Scene.ac_fbx_path = bpy.props.StringProperty(
        name="FBX", subtype='FILE_PATH',
        description="FBX file exported from Archicad")
    bpy.types.Scene.ac_target_collection = bpy.props.StringProperty(
        name="Target", default="ARCHICAD MODEL",
        description="Collection that holds the Archicad model in the scene; created on the first update if missing")
    bpy.types.Scene.ac_temp_collection = bpy.props.StringProperty(
        name="Temp", default="__TEMP_FBX__",
        description="Working collection for the import, emptied after each update; don't render it")
    bpy.types.Scene.ac_clear_missing = bpy.props.BoolProperty(
        name="Clear missing objects", default=True,
        description="Empty the mesh of objects no longer in the FBX instead of deleting them")
    bpy.types.Scene.ac_autoindex = bpy.props.BoolProperty(
        name="Auto pass index for new", default=True,
        description="Give each new object the lowest pass index not yet used in the target collection")
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.ac_fbx_path
    del bpy.types.Scene.ac_target_collection
    del bpy.types.Scene.ac_temp_collection
    del bpy.types.Scene.ac_clear_missing
    del bpy.types.Scene.ac_autoindex

