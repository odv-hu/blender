"""Archicad FBX Updater: update an Archicad model in the scene from a new FBX export.

Groups the import by surface (material) and keeps the Blender-side materials,
pass indices, modifiers and custom properties of existing objects.
Objects are matched by the surface they stand for, stored on the object, not by
their name, which Blender suffixes when the name is taken elsewhere (#37).
"""

import re
from math import radians

import bmesh
import bpy
import numpy as np
from mathutils import Matrix
from mathutils.bvhtree import BVHTree


DUP_SUFFIX = re.compile(r"^(.*)\.(\d{3})$")

# Custom property on each object the updater manages: the Archicad surface it stands for.
SURFACE_KEY = "odv_surface"

# A new face whose centre lies this close (scene units, metres) to an old face
# facing the same way keeps that face's material slot (#38).
FACE_MATCH_DISTANCE = 0.001


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def canonical(name):
    """Felulet-feher.001 -> Felulet-feher"""
    m = DUP_SUFFIX.match(name)
    return m.group(1) if m else name


def surface_of(obj):
    """The surface an object stands for.

    The stored surface name if the updater has set it, else the object's name
    without a .001 suffix (objects from earlier versions).
    """
    value = obj.get(SURFACE_KEY)
    if isinstance(value, str) and value:
        return value
    return canonical(obj.name)


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


# ---------------------------------------------------------------------------
# the transform: element-structured input -> surface-structured scene
# ---------------------------------------------------------------------------

# Attribute data types: (foreach property, components, numpy dtype).
ATTR_TYPES = {
    'FLOAT': ('value', 1, np.float32), 'INT': ('value', 1, np.int32),
    'FLOAT_VECTOR': ('vector', 3, np.float32), 'FLOAT_COLOR': ('color', 4, np.float32),
    'BYTE_COLOR': ('color', 4, np.float32), 'BOOLEAN': ('value', 1, bool),
    'FLOAT2': ('vector', 2, np.float32), 'INT32_2D': ('value', 2, np.int32),
    'INT16_2D': ('value', 2, np.int32), 'INT8': ('value', 1, np.int32),
    'QUATERNION': ('value', 4, np.float32), 'FLOAT4X4': ('value', 16, np.float32),
}
DOMAINS = ('POINT', 'EDGE', 'FACE', 'CORNER')
# Written from the topology arrays, not copied as attributes.
TOPOLOGY = {'position', 'material_index'}


def _get(collection, prop, n, comps, dtype):
    a = np.empty(n * comps, dtype)
    collection.foreach_get(prop, a)
    return a.reshape(n, comps) if comps > 1 else a


def _attributes(me):
    """{name: (domain, data_type)} of the mesh's attributes worth carrying over: UV
    maps, custom normals, sharp edges and faces, colours and any other generic layer.
    Internal ones (selection, '.' prefix) and the topology are left out."""
    return {a.name: (a.domain, a.data_type) for a in me.attributes
            if not a.name.startswith('.') and a.name not in TOPOLOGY
            and a.domain in DOMAINS and a.data_type in ATTR_TYPES}


def _world_matrix(obj):
    """The object's world matrix from its own transform and its parents', so it is
    right even before the depsgraph has updated matrix_world (as after a script set
    the transform). Parents other than objects fall back to matrix_world."""
    if obj.parent is None:
        return obj.matrix_basis.copy()
    if obj.parent_type != 'OBJECT':
        return obj.matrix_world.copy()
    return _world_matrix(obj.parent) @ obj.matrix_parent_inverse @ obj.matrix_basis


def _mesh_arrays(obj):
    """One object's mesh as numpy arrays, positions in world space."""
    me = obj.data
    nv, ne, nl, nf = len(me.vertices), len(me.edges), len(me.loops), len(me.polygons)
    co = _get(me.vertices, 'co', nv, 3, np.float64)
    m = np.array(_world_matrix(obj), np.float64)
    co = co @ m[:3, :3].T + m[:3, 3]
    d = {'co': co, 'edges': _get(me.edges, 'vertices', ne, 2, np.int64),
         'corner_vert': _get(me.loops, 'vertex_index', nl, 1, np.int64),
         'corner_edge': _get(me.loops, 'edge_index', nl, 1, np.int64),
         'loop_start': _get(me.polygons, 'loop_start', nf, 1, np.int64),
         'loop_total': _get(me.polygons, 'loop_total', nf, 1, np.int64),
         'material_index': _get(me.polygons, 'material_index', nf, 1, np.int64),
         'size': {'POINT': nv, 'EDGE': ne, 'FACE': nf, 'CORNER': nl}, 'attrs': {}}
    for name, (domain, dtype) in _attributes(me).items():
        prop, comps, npt = ATTR_TYPES[dtype]
        a = _get(me.attributes[name].data, prop, d['size'][domain], comps, npt)
        if name == 'custom_normal' and dtype == 'FLOAT_VECTOR':
            # free (object-space) normals turn with the object; encoded ones (INT16_2D,
            # relative to each corner's fan) do not need to
            nm = np.linalg.inv(m[:3, :3]).T
            a = a @ nm.T
            a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
            a = a.astype(np.float32)
        d['attrs'][name] = a
    return d


def _concatenate(parts):
    """All objects as one set of arrays, as a join would make them."""
    out = {}
    offs = {k: np.cumsum([0] + [p['size'][k] for p in parts]) for k in DOMAINS}
    out['co'] = np.concatenate([p['co'] for p in parts])
    out['edges'] = np.concatenate([p['edges'] + offs['POINT'][i] for i, p in enumerate(parts)])
    out['corner_vert'] = np.concatenate([p['corner_vert'] + offs['POINT'][i] for i, p in enumerate(parts)])
    out['corner_edge'] = np.concatenate([p['corner_edge'] + offs['EDGE'][i] for i, p in enumerate(parts)])
    out['loop_start'] = np.concatenate([p['loop_start'] + offs['CORNER'][i] for i, p in enumerate(parts)])
    out['loop_total'] = np.concatenate([p['loop_total'] for p in parts])
    kinds = {}
    for p in parts:
        for name, a in p['attrs'].items():
            kinds.setdefault(name, (a.dtype, a.shape[1:]))
    out['attrs'] = {}
    for name, (dtype, tail) in kinds.items():
        domain = next(p['domains'][name] for p in parts if name in p['attrs'])
        out['attrs'][name] = (domain, np.concatenate([
            p['attrs'][name] if name in p['attrs'] else np.zeros((p['size'][domain],) + tail, dtype)
            for p in parts]))
    return out


def _build_mesh(name, mat, all_, faces):
    """A new mesh of the given faces (indices into the joined arrays), with every
    attribute carried over and `mat` in its only slot."""
    ls, lt = all_['loop_start'][faces], all_['loop_total'][faces]
    corners = np.repeat(ls, lt) + (np.arange(int(lt.sum())) - np.repeat(np.cumsum(lt) - lt, lt))
    verts, vmap = np.unique(all_['corner_vert'][corners], return_inverse=True)
    edges, emap = np.unique(all_['corner_edge'][corners], return_inverse=True)
    vindex = np.full(len(all_['co']), -1, np.int64)
    vindex[verts] = np.arange(len(verts))
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.edges.add(len(edges))
    me.loops.add(len(corners))
    me.polygons.add(len(faces))
    me.vertices.foreach_set('co', all_['co'][verts].astype(np.float32).ravel())
    me.edges.foreach_set('vertices', vindex[all_['edges'][edges]].astype(np.int32).ravel())
    me.loops.foreach_set('vertex_index', vmap.astype(np.int32))
    me.loops.foreach_set('edge_index', emap.astype(np.int32))
    me.polygons.foreach_set('loop_start', (np.cumsum(lt) - lt).astype(np.int32))
    pick = {'POINT': verts, 'EDGE': edges, 'FACE': faces, 'CORNER': corners}
    for aname, (domain, data) in all_['attrs'].items():
        dtype = all_['types'][aname]
        prop = ATTR_TYPES[dtype][0]
        attr = me.attributes.get(aname) or me.attributes.new(aname, dtype, domain)
        attr.data.foreach_set(prop, np.ascontiguousarray(data[pick[domain]]).ravel())
    for i, uv in enumerate(all_['uv_order']):
        if uv in me.uv_layers:
            if uv == all_['uv_active']:
                me.uv_layers.active = me.uv_layers[uv]
            if uv == all_['uv_render']:
                me.uv_layers[uv].active_render = True
    me.materials.append(mat)
    me.update()
    return me


def bucket_by_material(objects, temp_col):
    """One object per surface, from mesh data directly (#16).

    Returns {material_name: object}. The grouping key is the material on each
    polygon, which is what Archicad's surface assignment became on export. Works
    like joining the import, applying the transform and separating by material,
    but with numpy on the mesh data instead of operators: independent of the
    active window, view layer and selection, and faster on large models. Faces
    without a material are left out, as before; so are loose vertices and edges.
    """
    meshes = [o for o in objects if o.type == 'MESH' and o.data and len(o.data.polygons)]
    if not meshes:
        return {}
    parts, keys, mats = [], [], {}
    for o in meshes:
        part = _mesh_arrays(o)
        part['domains'] = {n: dom for n, (dom, _t) in _attributes(o.data).items()}
        parts.append(part)
        slots = [s.material for s in o.material_slots] or [None]
        codes = []                    # material per slot as an integer, -1 for none
        for m in slots:
            if m is None:
                codes.append(-1)
            else:
                codes.append(list(mats).index(m.name) if m.name in mats else len(mats))
                mats.setdefault(m.name, m)
        idx = np.clip(part['material_index'], 0, len(slots) - 1)
        keys.append(np.array(codes, np.int64)[idx])
    all_ = _concatenate(parts)
    types = {}
    for o in meshes:
        for n, (_dom, t) in _attributes(o.data).items():
            types.setdefault(n, t)
    all_['types'] = types
    first = meshes[0].data
    all_['uv_order'] = [uv.name for uv in first.uv_layers]
    all_['uv_active'] = first.uv_layers.active.name if first.uv_layers.active else None
    all_['uv_render'] = next((uv.name for uv in first.uv_layers if uv.active_render), None)
    face_key = np.concatenate(keys)
    order = np.argsort(face_key, kind='stable')          # faces grouped by material, in order
    bounds = np.searchsorted(face_key[order], np.arange(len(mats) + 1))
    names = list(mats)

    result = {}
    for code in sorted(range(len(names)), key=lambda c: names[c]):
        name = names[code]
        faces = order[bounds[code]:bounds[code + 1]]
        if not len(faces):
            continue
        me = _build_mesh(name, mats[name], all_, faces)
        obj = bpy.data.objects.new(name, me)
        temp_col.objects.link(obj)
        obj.name = name
        result[name] = obj

    # The imported pieces are used up, as with a join. One batch: removing objects one
    # by one updates the relations each time and is slow with thousands of them.
    data = {o.data for o in meshes}
    bpy.data.batch_remove(meshes)
    bpy.data.batch_remove([d for d in data if d.users == 0])
    return result


# ---------------------------------------------------------------------------
# optional geometry clean-up (#10)
# ---------------------------------------------------------------------------

def merge_by_distance(mesh, distance):
    """Weld vertices closer than `distance`, then remove what that degenerates.

    The FBX arrives with every triangle on its own vertices; welding makes the
    surfaces connected. Corner data (UVs, imported normals) is kept per corner.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=distance)
    # collapses edges shorter than `distance` and faces without area
    bmesh.ops.dissolve_degenerate(bm, dist=distance, edges=bm.edges)
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(mesh)
    bm.free()


def smooth_by_angle(mesh, angle):
    """Shade smooth, sharp where neighbouring faces meet at more than `angle`.

    The FBX importer stores the exported normals as custom normals, which
    override smooth and sharp shading, so they are removed first. Stored in the
    mesh, not as a modifier, so it does not stack with modifiers on the object.
    """
    if mesh.has_custom_normals:
        attr = mesh.attributes.get("custom_normal")
        if attr is not None:
            mesh.attributes.remove(attr)
    mesh.shade_smooth()
    mesh.set_sharp_from_angle(angle=angle)


def clean_up(objects, scene):
    if not (scene.ac_merge_by_distance or scene.ac_smooth_by_angle):
        return
    for obj in objects:
        if scene.ac_merge_by_distance:
            merge_by_distance(obj.data, scene.ac_merge_distance)
        if scene.ac_smooth_by_angle:
            smooth_by_angle(obj.data, scene.ac_smooth_angle)


# ---------------------------------------------------------------------------
# update steps
# ---------------------------------------------------------------------------

def face_slots_from(old_mesh, old_matrix, new_mesh, n_slots):
    """Material slot for each face of `new_mesh`, taken from the old face it lies on.

    Keeps faces assigned to another slot in Blender (#38). A new face whose
    centre lies on an old face (within FACE_MATCH_DISTANCE, facing the same way)
    gets that face's slot; new or moved faces get slot 0. Returns None when there
    is nothing to carry over (one slot, or every old face in slot 0).
    """
    if n_slots < 2 or old_mesh is None or not len(old_mesh.polygons):
        return None
    old_slots = [0] * len(old_mesh.polygons)
    old_mesh.polygons.foreach_get("material_index", old_slots)
    if not any(old_slots):
        return None

    verts = [old_matrix @ v.co for v in old_mesh.vertices]
    tree = BVHTree.FromPolygons(verts, [tuple(p.vertices) for p in old_mesh.polygons])
    slots = []
    for poly in new_mesh.polygons:
        best, best_dist = 0, None
        for _loc, normal, index, dist in tree.find_nearest_range(poly.center, FACE_MATCH_DISTANCE):
            if index is None or normal.dot(poly.normal) < 0.99:
                continue
            if best_dist is None or dist < best_dist:
                best, best_dist = old_slots[index], dist
        slots.append(best if best < n_slots else 0)
    return slots


def swap_geometry(existing, incoming):
    """Keep the object shell -- pass_index, modifiers, custom props all survive.

    Returns the number of faces carried over to a slot other than the first.
    """
    old_mesh = existing.data
    kept = [s.material for s in existing.material_slots]
    if not kept:
        # an object emptied by an earlier version lost its slots: take the FBX's
        kept = list(incoming.data.materials)
    slots = face_slots_from(old_mesh, existing.matrix_world.copy(), incoming.data, len(kept))

    existing.data = incoming.data
    existing.matrix_world = Matrix.Identity(4)

    existing.data.materials.clear()
    for mat in kept:
        existing.data.materials.append(mat)
    if slots is not None:
        existing.data.polygons.foreach_set("material_index", slots)
        existing.data.update()

    bpy.data.objects.remove(incoming, do_unlink=True)
    if old_mesh and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    return sum(1 for i in slots if i) if slots else 0


def clear_geometry(obj):
    """Empty the object, keeping its material slots for when the surface returns (#38)."""
    old = obj.data
    if old is not None and not len(old.polygons):
        return  # already empty
    empty = bpy.data.meshes.new(f"{obj.name}_EMPTY")
    for mat in (old.materials if old is not None else []):
        empty.materials.append(mat)
    obj.data = empty
    if old and old.users == 0:
        bpy.data.meshes.remove(old)


def rank_for_surface(obj, surface):
    """Sort key: which of several objects standing for one surface gets updated."""
    return (
        obj.get(SURFACE_KEY) != surface,     # set by the updater
        not (obj.data and len(obj.data.polygons)),  # has geometry
        obj.name != surface,                 # carries the plain name
        -(len(obj.data.polygons) if obj.data else 0),
        obj.name,
    )


def objects_by_surface(objects):
    """{surface: object to update}, plus the other objects standing for the same surface."""
    groups = {}
    for obj in objects:
        if obj.type == 'MESH':
            groups.setdefault(surface_of(obj), []).append(obj)
    primary, duplicates = {}, []
    for surface, objs in groups.items():
        objs.sort(key=lambda o: rank_for_surface(o, surface))
        primary[surface] = objs[0]
        duplicates.extend(objs[1:])
    return primary, duplicates


def next_free_pass_index(collection):
    used = {o.pass_index for o in collection.objects}
    i = 1
    while i in used:
        i += 1
    return i


def surfaces_outside(surfaces, target, temp):
    """{surface: collection name} for the given surfaces that have objects outside
    the target and temp collections, anywhere in the file (#37)."""
    skip = set(target.objects) | set(temp.objects)
    found = {}
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj in skip or not obj.users_collection:
            continue
        surface = surface_of(obj)
        if surface in surfaces:
            found.setdefault(surface, obj.users_collection[0].name)
    return found


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

        target_created = bpy.data.collections.get(s.ac_target_collection) is None
        target = get_or_create_collection(s.ac_target_collection)
        temp = get_or_create_collection(s.ac_temp_collection)
        purge_collection(temp)

        imported = import_fbx(path)
        for obj in imported:
            move_exclusively(obj, temp)

        dedupe_materials(imported)
        incoming = bucket_by_material(imported, temp)
        clean_up(incoming.values(), s)

        existing, duplicates = objects_by_surface(target.objects)

        matched = set(existing) & set(incoming)
        added = set(incoming) - set(existing)
        gone = set(existing) - set(incoming)

        # surfaces that already have objects outside the target: usually a wrong Target
        elsewhere = surfaces_outside(added, target, temp)

        carried = {}
        for name in matched:
            obj = existing[name]
            n = swap_geometry(obj, incoming[name])
            obj[SURFACE_KEY] = name
            if n:
                carried[obj.name] = n

        for name in added:
            obj = incoming[name]
            obj[SURFACE_KEY] = name
            move_exclusively(obj, target)
            if s.ac_autoindex:
                obj.pass_index = next_free_pass_index(target)

        if s.ac_clear_missing:
            for name in gone:
                clear_geometry(existing[name])

        purge_collection(temp)
        purge_orphan_dupe_materials()

        summary = f"updated {len(matched)} | new {len(added)} | missing {len(gone)}"
        if duplicates:
            summary += f" | duplicates left {len(duplicates)}"
        self.report({'INFO'}, summary)
        if elsewhere:
            where = sorted(set(elsewhere.values()))
            self.report(
                {'WARNING'},
                f"{len(elsewhere)} new surfaces already have objects in {', '.join(where[:3])}"
                f"{' …' if len(where) > 3 else ''}: is Target '{target.name}' the model's collection?")
        elif target_created and incoming:
            self.report({'INFO'}, f"created collection '{target.name}'")
        print(f"[AC Updater] matched: {sorted(matched)}")
        print(f"[AC Updater] new:     {sorted(added)}")
        print(f"[AC Updater] missing: {sorted(gone)}")
        if carried:
            print(f"[AC Updater] faces kept in another slot: {dict(sorted(carried.items()))}")
        if duplicates:
            print(f"[AC Updater] duplicates left as they are: {sorted(o.name for o in duplicates)}")
        if elsewhere:
            print(f"[AC Updater] new surfaces with objects outside the target: {dict(sorted(elsewhere.items()))}")
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
        if s.ac_target_collection and bpy.data.collections.get(s.ac_target_collection) is None:
            col = layout.column(align=True)
            col.label(text=f"Target '{s.ac_target_collection}' not in this file:", icon='ERROR')
            col.label(text="it will be created, every surface added as new")

        box = layout.box()
        box.label(text="Options")
        box.prop(s, "ac_clear_missing")
        box.prop(s, "ac_autoindex")

        box = layout.box()
        box.label(text="Clean-up")
        row = box.row(heading="Merge by distance")
        row.prop(s, "ac_merge_by_distance", text="")
        sub = row.row()
        sub.active = s.ac_merge_by_distance
        sub.prop(s, "ac_merge_distance", text="")
        row = box.row(heading="Smooth by angle")
        row.prop(s, "ac_smooth_by_angle", text="")
        sub = row.row()
        sub.active = s.ac_smooth_by_angle
        sub.prop(s, "ac_smooth_angle", text="")

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
    bpy.types.Scene.ac_merge_by_distance = bpy.props.BoolProperty(
        name="Merge by distance", default=False,
        description=("Weld vertices closer than the distance and remove faces without area, "
                     "so each surface is connected instead of separate triangles"))
    bpy.types.Scene.ac_merge_distance = bpy.props.FloatProperty(
        name="Distance", default=0.0001, min=0.0, soft_max=0.01, precision=5,
        subtype='DISTANCE', unit='LENGTH',
        description="Vertices closer than this are welded")
    bpy.types.Scene.ac_smooth_by_angle = bpy.props.BoolProperty(
        name="Smooth by angle", default=False,
        description=("Shade smooth, sharp where faces meet at more than the angle. "
                     "Replaces the normals from the FBX; works on welded surfaces, so use it with Merge by distance"))
    bpy.types.Scene.ac_smooth_angle = bpy.props.FloatProperty(
        name="Angle", default=radians(30.0), min=0.0, max=radians(180.0),
        subtype='ANGLE',
        description="Edges between faces meeting at more than this angle stay sharp")
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
    del bpy.types.Scene.ac_merge_by_distance
    del bpy.types.Scene.ac_merge_distance
    del bpy.types.Scene.ac_smooth_by_angle
    del bpy.types.Scene.ac_smooth_angle

