"""Headless test of the Material ID tool (#19) on synthetic data.

Unpack the built extension into a folder named odv_tools, then run either

    blender --factory-startup -b --python tests/test_material_id.py -- <parent of odv_tools> <output folder>
    python3 tests/test_material_id.py -- <parent of odv_tools> <output folder>   (bpy module)

It builds two scenes sharing one collection, registers odv_tools and checks:
colours from names kept apart, repeat runs, scope of the AOV, copied and
hand-set colours, re-roll, removal, the beauty unchanged (pixel-exact, Cycles),
the AOV values for cut-out and half-transparent materials, survival of an update
through the Archicad FBX Updater, and unregister. It renders small Cycles
images on the CPU into the output folder; it never opens or saves a .blend.
Exit code 1 if a check fails.
"""
import os
import sys

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
PKG_PARENT, OUT = args[0], args[1]
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, PKG_PARENT)

bpy.ops.wm.read_factory_settings(use_empty=True)
import odv_tools  # noqa: E402
from odv_tools.blender import material_id as mid  # noqa: E402

odv_tools.register()

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


# --- scene setup -----------------------------------------------------------
s1 = bpy.context.scene
s1.name = "S1"
s1.render.engine = 'CYCLES'
s1.cycles.samples = 32
s1.cycles.device = 'CPU'
s1.cycles.use_denoising = False
s1.cycles.seed = 7
s1.render.threads_mode = 'FIXED'
s1.render.threads = 4
s1.render.resolution_x, s1.render.resolution_y = 200, 100
s1.view_settings.view_transform = 'AgX'

model = bpy.data.collections.new("MODEL")
s1.collection.children.link(model)


def principled(name, base=(0.8, 0.8, 0.8, 1)):
    m = bpy.data.materials.new(name)
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = base
    return m


def add_plane(name, size, loc, mat):
    me = bpy.data.meshes.new(name)
    h = size / 2
    me.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
    me.uv_layers.new()
    o = bpy.data.objects.new(name, me)
    o.location = loc
    if mat:
        me.materials.append(mat)
    model.objects.link(o)
    return o


# materials: plain, coloured, a leaf with an alpha mask (Principled Alpha), a
# leaf made with Mix Shader + Transparent, a constant half-transparent glass
wall = principled("Wall", (0.9, 0.85, 0.8, 1))
floor = principled("Floor", (0.3, 0.2, 0.1, 1))
names = ["Concrete", "Brick", "Steel", "Glass", "Wood", "Tile", "Plaster", "Roof"]
extra = [principled(n) for n in names]

leaf = principled("Leaf", (0.1, 0.5, 0.1, 1))
nt = leaf.node_tree
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
lt = nt.nodes.new("ShaderNodeMath")
lt.operation = 'LESS_THAN'
lt.inputs[1].default_value = 0.5
nt.links.new(tc.outputs["Generated"], sep.inputs[0])
nt.links.new(sep.outputs[0], lt.inputs[0])
nt.links.new(lt.outputs[0], nt.nodes["Principled BSDF"].inputs["Alpha"])  # left half opaque

leaf2 = bpy.data.materials.new("LeafMix")
nt2 = leaf2.node_tree
nt2.nodes.remove(nt2.nodes["Principled BSDF"])
tr = nt2.nodes.new("ShaderNodeBsdfTransparent")
df = nt2.nodes.new("ShaderNodeBsdfDiffuse")
mx = nt2.nodes.new("ShaderNodeMixShader")
tc2 = nt2.nodes.new("ShaderNodeTexCoord")
sep2 = nt2.nodes.new("ShaderNodeSeparateXYZ")
lt2 = nt2.nodes.new("ShaderNodeMath")
lt2.operation = 'LESS_THAN'
lt2.inputs[1].default_value = 0.5
nt2.links.new(tc2.outputs["Generated"], sep2.inputs[0])
nt2.links.new(sep2.outputs[0], lt2.inputs[0])
# factor 1 (left half) -> second shader = transparent: right half opaque
nt2.links.new(lt2.outputs[0], mx.inputs[0])
nt2.links.new(df.outputs[0], mx.inputs[1])
nt2.links.new(tr.outputs[0], mx.inputs[2])
nt2.links.new(mx.outputs[0], nt2.nodes["Material Output"].inputs["Surface"])

glass = principled("HalfGlass")
glass.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 0.5
veil = principled("Veil")
veil.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 0.2

add_plane("Floor", 4.0, (0, 0, 0), floor)
add_plane("Wall", 1.0, (-1.4, 0.4, 0.5), wall)
add_plane("Leaf", 1.0, (-0.2, 0.4, 1.0), leaf)
add_plane("LeafMix", 1.0, (0.9, 0.4, 1.0), leaf2)
add_plane("Glass", 0.6, (1.6, -0.6, 1.0), glass)
add_plane("Veil", 0.6, (0.5, -0.6, 1.0), veil)
add_plane("NoMat", 0.5, (-1.4, -0.6, 0.5), None)

cam = bpy.data.cameras.new("cam")
cam.type = 'ORTHO'
cam.ortho_scale = 4.0
co = bpy.data.objects.new("CamA", cam)
s1.collection.objects.link(co)
co.location = (0, 0, 10)
s1.camera = co
light = bpy.data.lights.new("sun", 'SUN')
lo = bpy.data.objects.new("sun", light)
s1.collection.objects.link(lo)
s1.world = bpy.data.worlds.new("w")

# second scene sharing the MODEL collection, two view layers
s2 = bpy.data.scenes.new("S2")
s2.collection.children.link(model)
s2.view_layers.new("Second")
s2.camera = co

def colours():
    return {m.name: mid.stored_colour(m) for m in bpy.data.materials}


def ours(m):
    return sorted(n.bl_idname for n in m.node_tree.nodes if n.get(mid.TAG))


def aov_layers():
    return {(sc.name, vl.name): [a.name for a in vl.aovs] for sc in bpy.data.scenes for vl in sc.view_layers}


# --- render helpers ---------------------------------------------------------
def render_pass(tag, aov=True):
    """Render S1, write beauty and (if enabled) the AOV to EXR, return float arrays."""
    ng = bpy.data.node_groups.new("comp_" + tag, "CompositorNodeTree")
    s1.compositing_node_group = ng
    rl = ng.nodes.new("CompositorNodeRLayers")
    rl.scene = s1
    outs = {}
    for sock in ("Image", mid.AOV_NAME) if aov else ("Image",):
        fo = ng.nodes.new("CompositorNodeOutputFile")
        fo.directory = OUT
        fo.file_name = f"{tag}_{sock}_"
        fo.format.media_type = 'IMAGE'
        fo.format.file_format = 'OPEN_EXR'
        fo.format.color_depth = '32'
        fo.file_output_items.new('RGBA', "px")
        ng.links.new(rl.outputs[sock], fo.inputs[0])
        outs[sock] = os.path.join(OUT, f"{tag}_{sock}_px.exr")
    bpy.ops.render.render(write_still=False, scene=s1.name)
    arrays = {}
    for sock, path in outs.items():
        img = bpy.data.images.load(path, check_existing=False)
        img.colorspace_settings.name = 'Non-Color'
        w, h = img.size
        arrays[sock] = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)
        bpy.data.images.remove(img)
    s1.compositing_node_group = None
    bpy.data.node_groups.remove(ng)
    return arrays


def px_at(arr, x, y):
    """Pixel at world (x, y) for the ortho camera: 4 x 2 units on 200 x 100 px."""
    col = int((x + 2.0) * 50)
    row = int((y + 1.0) * 50)
    return arr[row, col, :3]


def lin(c):
    return np.array(mid.to_scene_linear(c))


# --- 0. beauty before ---------------------------------------------------------
before = render_pass("before", aov=False)["Image"]

# --- 1. colours from names ------------------------------------------------------
check("derive_colour is deterministic", mid.derive_colour("Wall") == mid.derive_colour("Wall"))
check("derive_colour on the 8-bit grid", all(abs(c * 255 - round(c * 255)) < 1e-9 for c in mid.derive_colour("Wall")))
check("re-roll candidates differ", mid.derive_colour("Wall", 1) != mid.derive_colour("Wall"))
known = mid.derive_colour("Wall")
print("Wall ->", [round(c * 255) for c in known])

# --- 2. assign: active scene only ------------------------------------------------
s1.odv_matid_scenes = 'ACTIVE'
with bpy.context.temp_override(scene=s1):
    r = bpy.ops.odv.matid_assign()
check("assign finished", r == {'FINISHED'})
c1 = colours()
check("every material has a colour", all(v is not None for v in c1.values()), str(len(c1)))
expected, taken = {}, []
for n in sorted(c1):
    expected[n] = mid.first_distinct(n, taken)
    taken.append(expected[n])
check("colours = name-derived, kept apart, in name order", all(mid.same_colour(c1[n], expected[n]) for n in c1))
from_name = sum(mid.same_colour(c1[n], mid.derive_colour(n)) for n in c1)
dmin1 = min(mid.colour_distance(c1[a], c1[b]) for a in c1 for b in c1 if a < b)
check("first-run colours at least MIN_DISTANCE apart", dmin1 >= mid.MIN_DISTANCE, f"min delta E {dmin1:.1f}, {from_name}/{len(c1)} straight from the name")
check("ID nodes in every material", all(ours(m) for m in bpy.data.materials))
check("AOV only on S1", aov_layers() == {("S1", "ViewLayer"): ["odv_matid"], ("S2", "ViewLayer"): [], ("S2", "Second"): []}, str(aov_layers()))
check("AOV type COLOR", s1.view_layers[0].aovs["odv_matid"].type == 'COLOR')
check("Leaf follows Principled alpha", any(l.to_node.get(mid.TAG) and l.to_node.type == 'MATH' and l.from_node.type == 'MATH' and not l.from_node.get(mid.TAG) for l in leaf.node_tree.links))
check("LeafMix follows mix factor, inverted", "ShaderNodeMath" in ours(leaf2))
mixnode = next(n for n in glass.node_tree.nodes if n.get(mid.TAG) and n.type == 'MIX')
check("HalfGlass alpha 0.5 >= threshold: mask 1", mid.socket(mixnode.inputs, "Factor_Float").default_value == 1.0)
vmix = next(n for n in veil.node_tree.nodes if n.get(mid.TAG) and n.type == 'MIX')
check("Veil alpha 0.2 < threshold: mask 0", mid.socket(vmix.inputs, "Factor_Float").default_value == 0.0)
rgbnode = next(n for n in wall.node_tree.nodes if n.get(mid.TAG) and n.type == 'RGB')
check("RGB node holds the scene-linear colour", np.allclose(rgbnode.outputs[0].default_value[:3], lin(c1["Wall"]), atol=1e-6))
n_nodes_1 = {m.name: len(m.node_tree.nodes) for m in bpy.data.materials}

# --- 3. repeat run, then all scenes ----------------------------------------------
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_assign()
check("repeat run: same colours", colours() == c1)
check("repeat run: no extra nodes", {m.name: len(m.node_tree.nodes) for m in bpy.data.materials} == n_nodes_1)
s1.odv_matid_scenes = 'ALL'
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_assign()
check("ALL: AOV on every view layer, once", all(v == ["odv_matid"] for v in aov_layers().values()), str(aov_layers()))
check("ALL: same colours", colours() == c1)

# --- 4. hand-set colour is kept; copied material gets its own colour ----------------
mid.store_colour(extra[0], (1.0, 1.0, 0.0))
copy = wall.copy()  # carries Wall's colour and nodes
check("copy carries the property", mid.same_colour(mid.stored_colour(copy), c1["Wall"]))
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_assign()
c2 = colours()
check("hand-set colour kept and synced", mid.same_colour(c2["Concrete"], (1, 1, 0)) and np.allclose(next(n for n in extra[0].node_tree.nodes if n.get(mid.TAG) and n.type == 'RGB').outputs[0].default_value[:3], lin((1, 1, 0)), atol=1e-6))
check("Wall keeps its colour", mid.same_colour(c2["Wall"], c1["Wall"]))
check("copy gets a colour of its own", not mid.same_colour(c2[copy.name], c1["Wall"]), copy.name)
check("copy has one set of ID nodes", ours(copy).count("ShaderNodeOutputAOV") == 1)

# --- 5. re-roll ---------------------------------------------------------------
target = bpy.data.objects["Wall"]
with bpy.context.temp_override(scene=s1, object=target, active_object=target):
    check("reroll poll", bpy.ops.odv.matid_reroll.poll())
    bpy.ops.odv.matid_reroll()
    r1 = mid.stored_colour(wall)
    bpy.ops.odv.matid_reroll()
    r2 = mid.stored_colour(wall)
others = [v for k, v in colours().items() if k != "Wall"]
check("re-roll changes the colour", not mid.same_colour(r1, c1["Wall"]))
check("second re-roll differs again", not mid.same_colour(r1, r2))
check("re-roll counter stored", wall.get(mid.ROLL_PROP) == 2)
dmin = min(mid.colour_distance(r2, o) for o in others)
dmin_name = min(mid.colour_distance(c1["Wall"], o) for o in others)
check("re-rolled colour is distinct from all others", dmin > 10, f"min delta E {dmin:.1f} (name colour {dmin_name:.1f})")
with bpy.context.temp_override(scene=s1, object=bpy.data.objects["NoMat"], active_object=bpy.data.objects["NoMat"]):
    check("reroll disabled without material", not bpy.ops.odv.matid_reroll.poll())
c3 = colours()

# --- 6. render with IDs: beauty unchanged, AOV values -----------------------------
with_ids = render_pass("with")
diff = np.abs(with_ids["Image"] - before).max()
check("beauty unchanged with the ID nodes", diff == 0.0, f"max abs diff {diff}")
aov = with_ids[mid.AOV_NAME]
floor_c, wall_c, leaf_c, leaf2_c = (lin(c3[n]) for n in ("Floor", "Wall", "Leaf", "LeafMix"))
check("Wall pixel = Wall ID", np.allclose(px_at(aov, -1.6, 0.4), wall_c, atol=1e-4), str(px_at(aov, -1.6, 0.4)))
check("Floor pixel = Floor ID", np.allclose(px_at(aov, 0.0, -0.8), floor_c, atol=1e-4))
check("Leaf opaque half = Leaf ID", np.allclose(px_at(aov, -0.5, 0.4), leaf_c, atol=1e-4), str(px_at(aov, -0.5, 0.4)))
check("Leaf cut-out half = Floor ID (not Leaf + Floor)", np.allclose(px_at(aov, 0.1, 0.4), floor_c, atol=1e-4), str(px_at(aov, 0.1, 0.4)))
check("LeafMix opaque half = LeafMix ID", np.allclose(px_at(aov, 1.2, 0.4), leaf2_c, atol=1e-4), str(px_at(aov, 1.2, 0.4)))
check("LeafMix cut-out half = Floor ID", np.allclose(px_at(aov, 0.6, 0.4), floor_c, atol=1e-4), str(px_at(aov, 0.6, 0.4)))
g = px_at(aov, 1.6, -0.6)
check("HalfGlass (alpha = threshold) = HalfGlass ID, exact", np.allclose(g, lin(c3["HalfGlass"]), atol=1e-4), str(g))
v = px_at(aov, 0.5, -0.6)
ratio = v / floor_c
print(f"INFO behind Veil (alpha 0.2): {v.round(4)}, floor ID x {ratio.round(3)}")
check("Veil (alpha < threshold) shows the floor ID, dimmed by the veil", np.allclose(ratio, ratio.mean(), atol=0.02) and 0.7 < ratio.mean() < 0.9)
check("object without material = black", np.allclose(px_at(aov, -1.4, -0.6), 0, atol=1e-6))
# anti-aliasing: share of pixels that are exactly one ID colour
ids = np.stack([lin(c) for c in c3.values()] + [np.zeros(3)])
flat = aov[..., :3].reshape(-1, 3)
exact = np.min(np.abs(flat[:, None, :] - ids[None, :, :]).max(axis=2), axis=1) < 1e-4
print(f"INFO pixels exactly one ID colour: {exact.sum()}/{exact.size} ({100 * exact.mean():.1f}%), filter width {s1.cycles.filter_width}")

# --- 6b. remove, beauty unchanged, assign again -----------------------------------
c_pre = colours()
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_remove()
after = render_pass("after", aov=False)["Image"]
d2 = np.abs(after - before).max()
check("beauty unchanged after remove", d2 == 0.0, f"max abs diff {d2}")
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_assign()
check("assign after remove: same colours", colours() == c_pre)

# --- 7. update through the Archicad FBX Updater keeps the ID nodes ------------------
fbx_ok = hasattr(bpy.ops.export_scene, "fbx")
if fbx_ok:
    try:
        tmp = bpy.data.scenes.new("FBXSRC")
        src_col = tmp.collection
        for n, m in (("e1", wall), ("e2", floor), ("e3", extra[1])):
            me = bpy.data.meshes.new(n)
            me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
            me.materials.append(m)
            o = bpy.data.objects.new(n, me)
            src_col.objects.link(o)
        fbx_path = os.path.join(OUT, "model.fbx")
        with bpy.context.temp_override(scene=tmp):
            for o in src_col.objects:
                o.select_set(True)
            bpy.ops.export_scene.fbx(filepath=fbx_path, use_selection=False, object_types={'MESH'})
        bpy.data.scenes.remove(tmp)
        s1.ac_fbx_path = fbx_path
        s1.ac_target_collection = "MODEL"
        # target objects are named after their material, as the updater makes them
        for o in list(model.objects):
            if o.data and o.data.materials and o.data.materials[0]:
                o.name = o.data.materials[0].name
        before_nodes = {m: ours(bpy.data.materials[m]) for m in ("Wall", "Floor", "Brick")}
        with bpy.context.temp_override(scene=s1, view_layer=s1.view_layers[0]):
            r = bpy.ops.odv.ac_update_from_fbx()
        check("FBX update ran", r == {'FINISHED'})
        after_nodes = {m: ours(bpy.data.materials[m]) for m in ("Wall", "Floor", "Brick")}
        check("ID nodes survive the FBX update", after_nodes == before_nodes)
        check("ID colours survive the FBX update",
              all(mid.same_colour(mid.stored_colour(bpy.data.materials[m]), c3[m]) for m in ("Wall", "Floor", "Brick")))
        check("no .001 materials left", not any(m.name.endswith(".001") for m in bpy.data.materials), str([m.name for m in bpy.data.materials]))
    except Exception as e:  # report, don't hide
        check("FBX update section", False, repr(e))
else:
    print("SKIP FBX exporter not available")

# --- 8. remove --------------------------------------------------------------
c4 = colours()
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_remove()
check("remove: no ID nodes left", not any(ours(m) for m in bpy.data.materials))
check("remove: no AOV left", all(v == [] for v in aov_layers().values()), str(aov_layers()))
check("remove: colours kept", colours() == c4)
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_assign()
check("assign after the FBX update and remove: same colours", colours() == c4)
with bpy.context.temp_override(scene=s1):
    bpy.ops.odv.matid_remove(forget=True)
check("remove(forget): properties gone", not any(mid.PROP in m or mid.ROLL_PROP in m for m in bpy.data.materials))

# --- 9. unregister ---------------------------------------------------------------
odv_tools.unregister()
check("unregister: operators gone", not hasattr(bpy.types, "ODV_OT_matid_assign") and not hasattr(bpy.types.Scene, "odv_matid_scenes"))

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
