"""Material ID: one fixed flat colour per material, rendered to an AOV.

Each material gets an ID colour derived from its name, kept apart from the
colours already given, and stored on the material; and a few tagged nodes that write that colour to the AOV
`odv_matid`. The surface shader is not touched, so the beauty render does not
change. The AOV is enabled on the view layers of the chosen scenes.
"""

import colorsys
import hashlib
import itertools

import bpy
from mathutils import Color


AOV_NAME = "odv_matid"
PROP = "odv_matid"            # on the material: the ID colour, sRGB display values
ROLL_PROP = "odv_matid_roll"  # on the material: how often the colour was re-rolled
TAG = "odv_matid"             # on our nodes: marks them as ours

# Colours are picked from a coarse grid of saturation and value, so that no
# two levels are too close, and never darker than 0.55: black is what
# background and objects without a material give.
SATURATIONS = (0.45, 0.7, 0.95)
VALUES = (0.55, 0.78, 1.0)
REROLL_CANDIDATES = 16
# A new colour must be at least this far (CIE76 delta E) from those already
# given; with 65 materials, colours straight from the names had 10 pairs closer
# than 5 and one identical pair.
MIN_DISTANCE = 15.0
FIRST_CANDIDATES = 64
DEFAULT_THRESHOLD = 0.5  # Blender's default view layer Alpha Threshold
EPS = 1e-4


# ---------------------------------------------------------------------------
# colours
# ---------------------------------------------------------------------------

def derive_colour(name, k=0):
    """A colour from the material name: the same name always gives the same colour.

    `k` > 0 gives further candidates for the same name (re-roll). The result
    is on the 8-bit grid (n/255), so it is exact in 8- and 16-bit files.
    """
    key = name if k == 0 else f"{name}#{k}"
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    hue = int.from_bytes(digest[:4], "big") / 2 ** 32
    sat = SATURATIONS[digest[4] % len(SATURATIONS)]
    val = VALUES[digest[5] % len(VALUES)]
    rgb = colorsys.hsv_to_rgb(hue, sat, val)
    return tuple(round(c * 255) / 255 for c in rgb)


def _lab(c):
    """sRGB display colour -> CIELAB (D65), for perceptual distance."""
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    r, g, b = lin
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def colour_distance(a, b):
    """CIE76 delta E between two sRGB display colours; about 2.3 is just noticeable."""
    la, lb = _lab(a), _lab(b)
    return sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5


def same_colour(a, b):
    return all(round(p * 255) == round(q * 255) for p, q in zip(a, b))


def stored_colour(mat):
    """The material's ID colour, or None if it has none (or an unusable one)."""
    value = mat.get(PROP)
    try:
        c = tuple(float(x) for x in value)
    except TypeError:
        return None
    if len(c) != 3:
        return None
    return tuple(min(max(x, 0.0), 1.0) for x in c)


def store_colour(mat, colour):
    mat[PROP] = list(colour)
    mat.id_properties_ui(PROP).update(
        subtype='COLOR_GAMMA', min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        description="Material ID colour (odv tools), as it appears in a file written with the Standard view")


def most_distinct(name, others, first_k):
    """Of the re-roll candidates first_k .. first_k + n, the one farthest from all `others`."""
    best, best_d = None, -1.0
    for k in range(first_k, first_k + REROLL_CANDIDATES):
        c = derive_colour(name, k)
        d = min((colour_distance(c, o) for o in others), default=1000.0)
        if d > best_d:
            best, best_d = c, d
    return best


def first_distinct(name, others):
    """The first candidate for `name` at least MIN_DISTANCE from all `others`.

    Candidate 0 is the colour of the name itself. If no candidate is far
    enough, the most distinct one.
    """
    best, best_d = None, -1.0
    for k in range(FIRST_CANDIDATES):
        c = derive_colour(name, k)
        d = min((colour_distance(c, o) for o in others), default=1000.0)
        if d >= MIN_DISTANCE:
            return c
        if d > best_d:
            best, best_d = c, d
    return best


def closest_pairs(colours, n=5):
    """The n closest pairs of {name: colour}, as (distance, name, name)."""
    pairs = [(colour_distance(colours[a], colours[b]), a, b)
             for a, b in itertools.combinations(sorted(colours), 2)]
    pairs.sort()
    return pairs[:n]


# ---------------------------------------------------------------------------
# materials and nodes
# ---------------------------------------------------------------------------

def editable(mat):
    return (mat.node_tree is not None and mat.library is None
            and mat.override_library is None and not mat.is_grease_pencil)


def candidate_materials():
    """(editable, skipped) materials of the file. Grease Pencil materials are left out."""
    mats = [m for m in bpy.data.materials if not m.is_grease_pencil]
    ok = [m for m in mats if editable(m)]
    return ok, [m for m in mats if not editable(m)]


def socket(sockets, identifier):
    for s in sockets:
        if s.identifier == identifier:
            return s
    raise KeyError(identifier)


def active_output(nt):
    outs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    for n in outs:
        if n.is_active_output and n.target in {'ALL', 'CYCLES'}:
            return n
    for n in outs:
        if n.is_active_output:
            return n
    return outs[0] if outs else None


def upstream(sock):
    """The node feeding `sock`, through reroutes, or None."""
    while sock.is_linked:
        link = sock.links[0]
        if not link.is_valid or link.is_muted:
            return None, None
        node = link.from_node
        if node.type == 'REROUTE':
            sock = node.inputs[0]
            continue
        return node, link.from_socket
    return None, None


def alpha_of(nt):
    """Where the material's transparency comes from: (socket, constant, invert).

    Follows the Surface of the active Material Output to a Principled BSDF
    (its Alpha) or to a Mix Shader with a Transparent BSDF on one side (its
    factor). (None, 1.0, False) means opaque or not recognised.
    """
    out = active_output(nt)
    if out is None:
        return None, 1.0, False
    node, _ = upstream(out.inputs["Surface"])
    if node is None:
        return None, 1.0, False
    if node.type == 'BSDF_PRINCIPLED':
        a = node.inputs["Alpha"]
        src, src_socket = upstream(a)
        if src is not None:
            return src_socket, 1.0, False
        return None, float(a.default_value), False
    if node.type == 'MIX_SHADER':
        fac = node.inputs[0]
        first, _ = upstream(node.inputs[1])
        second, _ = upstream(node.inputs[2])
        if first is not None and first.type == 'BSDF_TRANSPARENT':
            invert = False   # factor 1 shows the second shader: alpha = factor
        elif second is not None and second.type == 'BSDF_TRANSPARENT':
            invert = True    # factor 1 shows the transparent one: alpha = 1 - factor
        else:
            return None, 1.0, False
        src, src_socket = upstream(fac)
        if src is not None:
            return src_socket, 1.0, invert
        value = float(fac.default_value)
        return None, (1.0 - value if invert else value), False
    return None, 1.0, False


def our_nodes(nt):
    return [n for n in nt.nodes if n.get(TAG)]


def remove_nodes(mat):
    nt = mat.node_tree
    nodes = our_nodes(nt)
    for n in nodes:
        nt.nodes.remove(n)
    return bool(nodes)


def to_scene_linear(colour):
    """sRGB display colour -> scene linear, in the file's working colour space."""
    return tuple(Color(colour).from_srgb_to_scene_linear())


def build_nodes(mat, colour, threshold=DEFAULT_THRESHOLD):
    """(Re)build the ID nodes: colour, masked by alpha >= threshold -> AOV Output.

    Returns True if the material's transparency is followed.

    Cycles writes the AOV of every surface a camera ray passes through, until
    it reaches one whose alpha is at least the view layer's Alpha Threshold,
    and adds the writes up. Without the mask, a cut-out leaf would write its ID
    over the whole card, added to the ID behind it. With it, a surface writes
    its ID exactly where Cycles treats it as the visible surface (the same rule
    as the Material Index pass) and black where the ray passes on.
    """
    nt = mat.node_tree
    remove_nodes(mat)

    out = active_output(nt)
    x, y = (out.location.x, out.location.y - 320) if out else (0.0, -320.0)

    frame = nt.nodes.new("NodeFrame")
    frame.label = "odv material ID"
    frame.name = "odv_matid"
    frame[TAG] = "frame"

    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.name = rgb.label = "odv_matid colour"
    rgb.outputs[0].default_value = (*to_scene_linear(colour), 1.0)

    mix = nt.nodes.new("ShaderNodeMix")
    mix.name = mix.label = "odv_matid mask"
    mix.data_type = 'RGBA'
    mix.blend_type = 'MIX'
    mix.clamp_factor = True
    socket(mix.inputs, "A_Color").default_value = (0.0, 0.0, 0.0, 1.0)
    nt.links.new(rgb.outputs[0], socket(mix.inputs, "B_Color"))

    aov = nt.nodes.new("ShaderNodeOutputAOV")
    aov.name = aov.label = "odv_matid AOV"
    aov.aov_name = AOV_NAME
    nt.links.new(socket(mix.outputs, "Result_Color"), aov.inputs["Color"])

    nodes = [rgb, mix, aov]
    src, constant, invert = alpha_of(nt)
    factor = socket(mix.inputs, "Factor_Float")
    if src is not None:
        cmp = nt.nodes.new("ShaderNodeMath")
        cmp.name = cmp.label = "odv_matid alpha >= threshold"
        if invert:   # alpha = 1 - factor, so alpha >= t  <=>  factor <= 1 - t
            cmp.operation = 'LESS_THAN'
            cmp.inputs[1].default_value = 1.0 - threshold + EPS
        else:
            cmp.operation = 'GREATER_THAN'
            cmp.inputs[1].default_value = threshold - EPS
        nt.links.new(src, cmp.inputs[0])
        nt.links.new(cmp.outputs[0], factor)
        nodes.insert(1, cmp)
    else:
        factor.default_value = 1.0 if constant >= threshold - EPS else 0.0

    for i, n in enumerate(nodes):
        n[TAG] = "node"
        n.parent = frame
        n.location = (x - 200 * (len(nodes) - 1 - i), y)
    return src is not None or constant < 1.0


def set_colour(mat, colour, threshold=DEFAULT_THRESHOLD):
    store_colour(mat, colour)
    return build_nodes(mat, colour, threshold)


# ---------------------------------------------------------------------------
# view layers
# ---------------------------------------------------------------------------

def target_scenes(context, which):
    return list(bpy.data.scenes) if which == 'ALL' else [context.scene]


def enable_aov(scenes):
    n = 0
    for scene in scenes:
        for vl in scene.view_layers:
            aov = vl.aovs.get(AOV_NAME)
            if aov is None:
                aov = vl.aovs.add()
                aov.name = AOV_NAME
                n += 1
            aov.type = 'COLOR'
    return n


def disable_aov(scenes):
    n = 0
    for scene in scenes:
        for vl in scene.view_layers:
            aov = vl.aovs.get(AOV_NAME)
            if aov is not None:
                vl.aovs.remove(aov)
                n += 1
    return n


# ---------------------------------------------------------------------------
# operators
# ---------------------------------------------------------------------------

def resolve_colours(mats):
    """{material: colour} for every material, keeping stored colours where possible.

    A new material gets the colour of its name, or, if that is closer than
    MIN_DISTANCE to a colour already given, the first further candidate for
    its name that is not (in name order, so the same names give the same
    colours). Stored colours are never changed. Materials that share a stored
    colour (a copied material carries its original's property) keep it only on
    the one the colour belongs to; the others get a colour of their own.
    """
    colours, by_colour, new = {}, {}, []
    for mat in sorted(mats, key=lambda m: m.name):
        c = stored_colour(mat)
        if c is None:
            new.append(mat)
        else:
            by_colour.setdefault(tuple(round(x * 255) for x in c), []).append((mat, c))

    for group in by_colour.values():
        owner = next((m for m, c in group if same_colour(c, derive_colour(m.name))), group[0][0])
        for mat, c in group:
            if mat is owner:
                colours[mat] = c
            else:
                new.append(mat)

    taken = list(colours.values())
    fresh = set()
    for mat in sorted(new, key=lambda m: m.name):
        c = first_distinct(mat.name, taken)
        colours[mat] = c
        taken.append(c)
        fresh.add(mat)
    return colours, fresh


class ODV_OT_matid_assign(bpy.types.Operator):
    bl_idname = "odv.matid_assign"
    bl_label = "Assign material IDs"
    bl_description = ("Give every material a fixed ID colour and write it to the odv_matid AOV, "
                      "enabled on the view layers of the chosen scenes. Existing colours are kept; "
                      "the beauty render does not change")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mats, skipped = candidate_materials()
        colours, fresh = resolve_colours(mats)

        threshold = context.view_layer.pass_alpha_threshold
        followed = []
        for mat, c in colours.items():
            if mat in fresh or not same_colour(c, stored_colour(mat) or (-1, -1, -1)):
                store_colour(mat, c)
            if build_nodes(mat, c, threshold):
                followed.append(mat.name)

        scenes = target_scenes(context, context.scene.odv_matid_scenes)
        added = enable_aov(scenes)

        named = {m.name: c for m, c in colours.items()}
        pairs = closest_pairs(named)
        msg = f"{len(colours)} materials ({len(fresh)} new colours), AOV on {len(scenes)} scene(s)"
        if skipped:
            msg += f", {len(skipped)} linked skipped"
        self.report({'INFO'}, msg)
        print(f"[odv matid] {msg}; AOV added to {added} view layer(s)")
        if followed:
            print(f"[odv matid] ID masked by alpha >= {threshold:g} in: {sorted(followed)}")
        if skipped:
            print(f"[odv matid] skipped (linked or without nodes): {sorted(m.name for m in skipped)}")
        for d, a, b in pairs:
            print(f"[odv matid] close colours: {a} / {b}  (delta E {d:.1f})")
        return {'FINISHED'}


class ODV_OT_matid_reroll(bpy.types.Operator):
    bl_idname = "odv.matid_reroll"
    bl_label = "Re-roll"
    bl_description = ("Give the active material a new ID colour, as different as possible "
                      "from the colours of all other materials")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        mat = obj.active_material if obj else None
        if mat is None:
            cls.poll_message_set("Select an object with a material")
            return False
        if not editable(mat):
            cls.poll_message_set("The active material is linked or has no nodes")
            return False
        return True

    def execute(self, context):
        mat = context.object.active_material
        roll = int(mat.get(ROLL_PROP, 0)) + 1
        others = [c for m in bpy.data.materials if m is not mat
                  for c in [stored_colour(m)] if c is not None]
        colour = most_distinct(mat.name, others, 1 + (roll - 1) * REROLL_CANDIDATES)
        mat[ROLL_PROP] = roll
        set_colour(mat, colour, context.view_layer.pass_alpha_threshold)
        hexa = "".join(f"{round(c * 255):02X}" for c in colour)
        self.report({'INFO'}, f"{mat.name}: #{hexa}")
        return {'FINISHED'}


class ODV_OT_matid_remove(bpy.types.Operator):
    bl_idname = "odv.matid_remove"
    bl_label = "Remove material IDs"
    bl_description = ("Remove the ID nodes from every material and the odv_matid AOV from every "
                      "view layer of every scene. The colours stay stored on the materials, so "
                      "assigning again gives the same colours")
    bl_options = {'REGISTER', 'UNDO'}

    forget: bpy.props.BoolProperty(
        name="Forget colours", default=False,
        description="Also delete the stored ID colours; assigning again then starts from the material names")

    def execute(self, context):
        mats, _ = candidate_materials()
        n_nodes = sum(remove_nodes(m) for m in mats)
        if self.forget:
            for m in mats:
                for key in (PROP, ROLL_PROP):
                    if key in m:
                        del m[key]
        n_aov = disable_aov(bpy.data.scenes)
        self.report({'INFO'}, f"ID nodes removed from {n_nodes} materials, AOV from {n_aov} view layer(s)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------

class ODV_PT_material_id(bpy.types.Panel):
    bl_label = "Material ID"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "odv"

    def draw(self, context):
        layout = self.layout
        s = context.scene
        row = layout.row(heading="Scenes")
        row.prop(s, "odv_matid_scenes", expand=True)
        col = layout.column()
        col.operator("odv.matid_assign", icon='COLOR')
        col.operator("odv.matid_remove", icon='X')

        obj = context.object
        mat = obj.active_material if obj else None
        box = layout.box()
        if mat is None:
            box.label(text="No active material")
            return
        box.label(text=mat.name, icon='MATERIAL')
        row = box.row()
        if PROP in mat:
            row.prop(mat, f'["{PROP}"]', text="")
        else:
            row.label(text="No ID colour yet")
        row.operator("odv.matid_reroll", icon='FILE_REFRESH')


# ---------------------------------------------------------------------------

classes = (
    ODV_OT_matid_assign,
    ODV_OT_matid_reroll,
    ODV_OT_matid_remove,
    ODV_PT_material_id,
)


def register():
    bpy.types.Scene.odv_matid_scenes = bpy.props.EnumProperty(
        name="Scenes",
        items=(
            ('ACTIVE', "Active", "Enable the ID AOV on the view layers of the active scene"),
            ('ALL', "All", "Enable the ID AOV on the view layers of every scene in the file"),
        ),
        default='ACTIVE',
        description="Scenes whose view layers get the odv_matid AOV. Materials are shared, so every material gets its colour either way")
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.odv_matid_scenes
