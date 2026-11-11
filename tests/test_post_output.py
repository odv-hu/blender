"""Headless test of Post-production output (#20, #21) on synthetic data.

Unpack the built extension into a folder named odv_tools, then run, with
BLENDER_USER_RESOURCES set to an empty folder of its own:

    blender --factory-startup -b --python-exit-code 1 --python tests/test_post_output.py -- <parent of odv_tools> <output folder>

Without BLENDER_USER_RESOURCES, a factory-startup Blender sees no enabled
extensions and removes the Python wheels that the installed extensions keep in
the shared user extensions folder (they come back on the next normal start).
The output folder is emptied first. Without --python-exit-code 1, Blender exits
with 0 even when the script fails.

It builds a scene with two materials and two cameras, registers odv_tools,
assigns material IDs, runs *Set up output* and renders small Cycles images on
the CPU into the output folder. It checks the set-up (output format, the ID
File Output node and its colour management), the layered PSD of a written
render per camera (layer names, visibility, blend mode, pixels against the
PNG files, the merged composite, the ICC profile), the ID colours, *Keep
separate files* off, a premultiplied TIFF beauty, a muted ID node, an F12-style
render saved from the render result, the Image Editor operator, a photo-match
compositor (render, Shadow Catcher pass and photo as separate layers, the
multiply added to the compositor, the stack against Blender's composite), the
extra passes of #22 (the Full preset: Cycles passes, File Output, Mix and
Denoise nodes, hidden PSD layers in their order and blend modes, mist and AO
stretched per image, the other layers bit-exact against their files; a
measurement of light groups added on display values against the beauty; the
Minimal preset taking everything out again; the Photo match preset in a photo
match without a second shadow layer), and unregister.

Not covered: the interactive Blender (the render thread, the timer and worker
thread that run there instead of the synchronous path used in background
mode), Photographer's render queue, opening the PSD in an image editor.
It never opens or saves a .blend. Exit code 1 if a check fails.
"""
import os
import shutil
import struct
import sys
import zlib

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
PKG_PARENT, OUT = args[0], os.path.abspath(args[1])
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
_left = [os.path.join(d, f) for d, _, fs in os.walk(OUT) for f in fs]
if _left:   # an empty folder held open (e.g. by Explorer) is fine, old files are not
    print(f"FAIL could not empty the output folder: {_left[:3]}")
    sys.exit(1)
sys.path.insert(0, PKG_PARENT)

bpy.ops.wm.read_factory_settings(use_empty=True)
import odv_tools  # noqa: E402
from odv_tools.blender import post_output as po  # noqa: E402
from odv_tools.blender.material_id import PROP  # noqa: E402

FAILED = []


def check(ok, text):
    print(("PASS " if ok else "FAIL ") + text)
    if not ok:
        FAILED.append(text)


# --- PSD decoding, for the files odv_tools writes ---------------------------

def read_psd(path):
    """Layers {name: (H, W, 4) uint16} and the composite (H, W, 4)."""
    with open(path, "rb") as f:
        _, _, nch, h, w, _, _ = struct.unpack(">4sH6xHIIHH", f.read(26))
        f.seek(struct.unpack(">I", f.read(4))[0], 1)
        res = f.read(struct.unpack(">I", f.read(4))[0])
        lmi_len = struct.unpack(">I", f.read(4))[0]
        lmi_start = f.tell()
        f.read(4)
        count = abs(struct.unpack(">h", f.read(2))[0])
        recs = []
        for _ in range(count):
            f.read(16)
            n = struct.unpack(">H", f.read(2))[0]
            chans = [struct.unpack(">hI", f.read(6)) for _ in range(n)]
            f.read(12)
            extra = f.read(struct.unpack(">I", f.read(4))[0])
            pos = 4 + struct.unpack(">I", extra[:4])[0]
            pos += 4 + struct.unpack(">I", extra[pos:pos + 4])[0]
            name = extra[pos + 1:pos + 1 + extra[pos]].decode()
            recs.append((name, chans))
        layers = {}
        for name, chans in recs:
            px = np.zeros((h, w, 4), np.uint16)
            for cid, length in chans:
                comp = struct.unpack(">H", f.read(2))[0]
                data = f.read(length - 2)
                if comp in (2, 3):
                    data = zlib.decompress(data)
                plane = np.frombuffer(data, ">u2").reshape(h, w).astype(np.uint16)
                if comp == 3:
                    plane = np.cumsum(plane, axis=1, dtype=np.uint16)
                px[..., 3 if cid == -1 else cid] = plane
            layers[name] = px
        f.seek(lmi_start + lmi_len)
        comp = struct.unpack(">H", f.read(2))[0]
        assert comp == 0
        composite = np.frombuffer(f.read(), ">u2").reshape(nch, h, w).transpose(1, 2, 0)
    icc = None
    if res[:6] == b"8BIM\x04\x0f":
        icc = res[12:12 + struct.unpack(">I", res[8:12])[0]]
    return layers, composite, icc


def raw(path):
    px, _ = po.read_image(path)
    return px


# --- scene ------------------------------------------------------------------

scene = bpy.context.scene
scene.name = "post"
r = scene.render
r.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 16
scene.cycles.seed = 1
r.threads_mode = 'FIXED'
r.threads = 4
r.resolution_x, r.resolution_y, r.resolution_percentage = 160, 90, 100
r.film_transparent = True
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
scene.world = world


def box(name, loc, size, colour):
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    scene.collection.objects.link(ob)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = colour
    me.materials.append(mat)
    return mat


wall = box("Wall", (0, 0, 0), (3, 0.2, 2), (0.8, 0.8, 0.8, 1))
brick = box("Brick", (0.4, -0.8, -0.3), (0.8, 0.8, 0.8), (0.6, 0.2, 0.1, 1))
cams = []
for i, (loc, rot) in enumerate((((0, -6, 0.5), (1.5, 0, 0)), ((3, -5, 1.2), (1.35, 0, 0.5)))):
    cam = bpy.data.objects.new(f"Cam{i + 1}", bpy.data.cameras.new(f"Cam{i + 1}"))
    cam.location, cam.rotation_euler = loc, rot
    scene.collection.objects.link(cam)
    cams.append(cam)
scene.camera = cams[0]

odv_tools.register()
check(bpy.ops.odv.matid_assign() == {'FINISHED'}, "Assign material IDs")

# --- set-up -----------------------------------------------------------------

r.filepath = os.path.join(OUT, "render", "shot")
check(bpy.ops.odv.post_setup() == {'FINISHED'}, "Set up output")
im = r.image_settings
check((im.file_format, im.color_depth, im.color_mode) == ('PNG', '16', 'RGBA'), "beauty: 16-bit PNG RGBA")
check(scene.odv_post.enabled and scene.odv_post.keep_separate and scene.odv_post.save_f12,
      "settings on after set-up")
node = po.id_node(scene)
check(node is not None, "ID File Output node in the scene's compositor group")
fmt = node.format
check((fmt.file_format, fmt.color_depth, fmt.color_mode) == ('PNG', '16', 'RGB'), "ID file: 16-bit PNG RGB")
check(fmt.color_management == 'OVERRIDE' and fmt.view_settings.view_transform == 'Standard'
      and fmt.view_settings.look == 'None', "ID file: Standard view")
link = node.inputs[0].links[0] if node.inputs[0].is_linked else None
check(link is not None and link.from_socket.name == "odv_matid", "ID node fed by the odv_matid AOV")
check(bpy.ops.odv.post_setup() == {'FINISHED'}
      and sum(1 for n in scene.compositing_node_group.nodes if n.bl_idname == "CompositorNodeOutputFile") == 1,
      "Set up twice: still one File Output node")

ids = {m.name: tuple(round(c * 255) * 257 for c in m[PROP]) for m in (wall, brick)}


def render(name, write=True):
    r.filepath = os.path.join(OUT, "render", name)
    bpy.ops.render.render(write_still=write)
    return os.path.join(OUT, "render", name)


# --- written renders, two cameras ---------------------------------------------

for cam in cams:
    scene.camera = cam
    stem = render(cam.name)
    ok = all(os.path.exists(stem + e) for e in (".png", "_matid.png", ".psd"))
    check(ok, f"{cam.name}: beauty, ID file and PSD next to each other")
    if not ok:
        continue
    s = po.psd.read_summary(stem + ".psd")
    check(s["layers"] == [("beauty", True, "norm"), ("matid", False, "norm")] and s["depth"] == 16
          and (s["width"], s["height"]) == (160, 90), f"{cam.name}: PSD layers beauty (visible) and matid (hidden), Normal, 16-bit")
    layers, composite, icc = read_psd(stem + ".psd")
    beauty = raw(stem + ".png")
    idpx = raw(stem + "_matid.png")
    check(np.array_equal(layers["beauty"], beauty), f"{cam.name}: beauty layer = beauty PNG, bit-exact")
    check(np.array_equal(layers["matid"][..., :3], idpx[..., :3]) and (layers["matid"][..., 3] == 65535).all(),
          f"{cam.name}: matid layer = ID PNG, opaque")
    check(np.array_equal(composite, po.psd.flatten_over_white(beauty)), f"{cam.name}: composite = beauty over white")
    # Blender 5.0 and 5.1 write PNGs without an ICC profile; then the PSD has none either.
    png_icc = po.read_image(stem + ".png")[1]
    check(icc == png_icc and (png_icc is None or len(icc) > 100) and (png_icc or bpy.app.version < (5, 2, 0)),
          f"{cam.name}: the beauty's ICC profile embedded ({len(icc or b'')} bytes)")
    check((beauty[..., 3] == 0).any() and (beauty[..., 3] == 65535).any(), f"{cam.name}: beauty has transparent and opaque pixels")
    colours = {tuple(c) for c in idpx[..., :3].reshape(-1, 3)}
    for mname, c in ids.items():
        check(c in colours, f"{cam.name}: exact ID colour of {mname} in the ID file")

# --- keep separate files off ----------------------------------------------------

scene.camera = cams[0]
scene.odv_post.keep_separate = False
stem = render("nokeep")
check(os.path.exists(stem + ".psd") and not os.path.exists(stem + ".png")
      and not os.path.exists(stem + "_matid.png") and not os.path.exists(os.path.join(OUT, "render", "matid.png")),
      "Keep separate files off: only the PSD is left")
scene.odv_post.keep_separate = True

# --- ID file on another drive: rename refused, the move has to copy -------------------

import errno  # noqa: E402

_rename = os.rename


def _cross_device(src, dst):
    raise OSError(errno.EXDEV, "cross-device link (simulated)")


os.rename = _cross_device
try:
    stem = render("xdrive")
finally:
    os.rename = _rename
check(os.path.exists(stem + ".psd") and os.path.exists(stem + "_matid.png")
      and not os.path.exists(os.path.join(OUT, "render", "matid.png")),
      "ID file on another drive (rename refused): copied next to the beauty, PSD written")

# --- premultiplied TIFF beauty ---------------------------------------------------

im.file_format = 'TIFF'
im.color_depth = '16'
im.color_mode = 'RGBA'
stem = render("tiff")
layers, _, _ = read_psd(stem + ".psd")
ref = raw(os.path.join(OUT, "render", "Cam1.png"))
a = ref[..., 3]
diff = np.abs(layers["beauty"].astype(int) - ref.astype(int))
check((layers["beauty"][..., 3] == a).all() and diff[a > 32767].max() <= 2,
      f"TIFF beauty (premultiplied) -> straight in the PSD: max colour difference "
      f"{int(diff[a > 32767].max())} where alpha > 0.5, against the PNG render")
im.file_format = 'PNG'

# --- muted ID node ---------------------------------------------------------------

node.mute = True
stem = render("muted")
s = po.psd.read_summary(stem + ".psd")
check(s["layers"] == [("beauty", True, "norm")], "ID node muted: PSD with the beauty only")
node.mute = False

# --- F12-style render (not written by Blender) -------------------------------------

stem = render("f12", write=False)
check(os.path.exists(stem + ".png") and os.path.exists(stem + ".psd") and os.path.exists(stem + "_matid.png"),
      "render without writing, Save F12 renders on: beauty saved from the render result, PSD written")
if os.path.exists(stem + ".png"):
    check(np.array_equal(raw(stem + ".png"), raw(os.path.join(OUT, "render", "Cam1.png"))),
          "saved F12 beauty = written beauty of the same camera, bit-exact")

scene.odv_post.save_f12 = False
stem = render("f12off", write=False)
check(not os.path.exists(stem + ".png") and not os.path.exists(stem + ".psd"),
      "Save F12 renders off: nothing saved")
check(bpy.ops.odv.post_save_render() == {'FINISHED'} and os.path.exists(stem + ".psd")
      and po.psd.read_summary(stem + ".psd")["layers"] == [("beauty", True, "norm"), ("matid", False, "norm")],
      "Image Editor operator: beauty and PSD saved afterwards")
other = os.path.join(OUT, "chosen", "picked.psd")
check(bpy.ops.odv.post_save_render(filepath=other) == {'FINISHED'} and os.path.exists(other)
      and os.path.exists(os.path.join(OUT, "chosen", "picked.png"))
      and os.path.exists(os.path.join(OUT, "chosen", "picked_matid.png"))
      and po.psd.read_summary(other)["layers"] == [("beauty", True, "norm"), ("matid", False, "norm")],
      "Image Editor operator with a chosen file: PSD, beauty and ID file at the chosen name")
check(os.path.exists(stem + "_matid.png"),
      "second save copies the ID file: the first PSD keeps its separate files")

# --- extra passes (#22) ------------------------------------------------------------------

s = scene.odv_post
vl = scene.view_layers[0]
for name in ("key", "fill"):
    vl.lightgroups.add().name = name
mask_aov = vl.aovs.add()
mask_aov.name, mask_aov.type = "mask", 'VALUE'
key = bpy.data.objects.new("Key", bpy.data.lights.new("Key", 'POINT'))
key.data.energy = 400.0
key.location = (-2, -3, 3)
scene.collection.objects.link(key)
key.lightgroup = "key"
world.lightgroup = "fill"
lamp = box("Lamp", (-1.0, -0.8, 0.6), (0.3, 0.3, 0.3), (1, 1, 1, 1))
lamp_bsdf = lamp.node_tree.nodes["Principled BSDF"]
lamp_bsdf.inputs["Emission Color"].default_value = (1.0, 0.6, 0.2, 1)
lamp_bsdf.inputs["Emission Strength"].default_value = 5.0
aov_out = lamp.node_tree.nodes.new("ShaderNodeOutputAOV")
aov_out.aov_name = "mask"
aov_out.inputs["Value"].default_value = 1.0
glass = box("Glass", (1.0, -1.5, 0.2), (0.5, 0.1, 0.8), (0.9, 0.95, 1.0, 1))
glass.node_tree.nodes["Principled BSDF"].inputs["Transmission Weight"].default_value = 1.0

check(bpy.ops.odv.post_preset(preset='FULL') == {'FINISHED'}, "Full preset")
check([k for k in po.PASSES if getattr(s, "pass_" + k)] == list(po.PRESETS["FULL"][2]),
      "Full preset ticks every pass except environment and albedo")
check(vl.use_pass_mist and vl.use_pass_ambient_occlusion and vl.use_pass_glossy_direct
      and vl.use_pass_glossy_indirect and vl.use_pass_glossy_color and vl.use_pass_transmission_direct
      and vl.use_pass_transmission_indirect and vl.use_pass_transmission_color and vl.use_pass_emit,
      "Full preset: the matching Cycles passes are on")
g = scene.compositing_node_group
aids, light = g.nodes.get(po.AIDS_NODE), g.nodes.get(po.LIGHT_NODE)
check(aids is not None and [i.name for i in aids.file_output_items] == ["mist", "ao"]
      and aids.format.color_mode == 'RGB' and aids.format.color_management == 'OVERRIDE'
      and aids.format.view_settings.view_transform == 'Raw',
      "mist and AO File Output: RGB, Raw view")
check(light is not None and [i.name for i in light.file_output_items]
      == ["light_key", "light_fill", "reflection", "refraction", "emission"]
      and light.format.color_mode == 'RGB' and light.format.color_management == 'FOLLOW_SCENE',
      "light File Output: light groups, reflection, refraction, emission; RGB, scene view transform")
check([i.name for i in node.file_output_items] == ["matid", "aov_mask"], "custom AOV on the ID node (Standard view)")
dn = sorted(n.name for n in g.nodes if n.name.startswith("odv_dn_"))
check(dn == ["odv_dn_light_fill", "odv_dn_light_key", "odv_dn_reflection", "odv_dn_refraction"]
      and all(g.nodes[n].bl_idname == "CompositorNodeDenoise" for n in dn),
      "a Denoise node per light group and for reflection and refraction")
mix = g.nodes.get("odv_mix_reflection_colour")
check(mix is not None and mix.blend_type == 'MULTIPLY'
      and po._socket(mix.inputs, "B_Color").links[0].from_socket.name == "Glossy Color"
      and po._socket(mix.inputs, "A_Color").links[0].from_node.name == "odv_mix_reflection_add",
      "reflection = (glossy direct + indirect) x glossy colour")
names_before = sorted(n.name for n in g.nodes)
check(bpy.ops.odv.post_setup() == {'FINISHED'} and sorted(n.name for n in g.nodes) == names_before,
      "Set up again: no extra nodes")
check(all(ok for ok, _ in po.status_lines(scene, vl)), "status box: every line ticked")

world.mist_settings.start, world.mist_settings.depth = 0.0, 50.0
stem = render("passes")
want_passes = [("beauty", True, "norm"), ("light_key", False, "lddg"), ("light_fill", False, "lddg"),
               ("reflection", False, "lddg"), ("refraction", False, "lddg"), ("emission", False, "lddg"),
               ("ao", False, "mul "), ("mist", False, "scrn"), ("aov_mask", False, "norm"),
               ("matid", False, "norm")]
ok = os.path.exists(stem + ".psd")
check(ok and po.psd.read_summary(stem + ".psd")["layers"] == want_passes,
      "extra passes: hidden layers in order (Add, Multiply, Screen, Normal) below matid, above beauty")
if ok:
    layers, composite, _ = read_psd(stem + ".psd")
    files = {role: raw(f"{stem}_{role}.png") for role, _, _ in want_passes[1:-1]}
    for role in ("mist", "ao"):
        v = layers[role]
        check(v[..., 0].min() == 0 and v[..., 0].max() == 65535 and (v[..., 0] == v[..., 1]).all()
              and (v[..., 0] == v[..., 2]).all(),
              f"{role}: greyscale stretched to 0-65535 (file {files[role][..., 0].min()}-{files[role][..., 0].max()})")
        check(np.array_equal(v[..., :3], po._stretch(files[role])), f"{role}: layer = its file, stretched")
    check(files["mist"][..., 0].min() > 0, "mist: the file does not reach black, so the stretch is exercised")
    check(all(np.array_equal(layers[role][..., :3], files[role][..., :3]) for role in files
              if role not in ("mist", "ao")),
          "light, reflection, refraction, emission and AOV layers = their files, bit-exact")
    check(all(files[role][..., :3].max() > 0 for role in files), "every extra pass has content")
    check(files["aov_mask"][..., :3].max() == 65535, "the custom AOV carries the mask")
    check(np.array_equal(composite, po.psd.flatten_over_white(raw(stem + ".png"))),
          "extra passes: composite unchanged (beauty over white)")

# Light groups added on display values against the beauty (#22: Add layers are aids).
# Every emitter in a light group, Standard view, no denoising, so that the light groups
# add up to the beauty in linear light.
lamp_ob = bpy.data.objects["Lamp"]
lamp_ob.lightgroup = "key"
view_before = scene.view_settings.view_transform
scene.view_settings.view_transform, scene.view_settings.look = 'Standard', 'None'
denoise_before = scene.cycles.use_denoising
scene.cycles.use_denoising = False
s.denoise = False
bpy.ops.odv.post_setup()
check(not any(n.name.startswith("odv_dn_") for n in g.nodes)
      and light.inputs["light_key"].links[0].from_socket.name == "Combined_key",
      "Denoise light passes off: Denoise nodes removed, light groups linked directly")
stem = render("lightsum")
L, _, _ = read_psd(stem + ".psd")
b = raw(stem + ".png").astype(np.float64) / 65535
op = b[..., 3] == 1.0


def lin(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def enc(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


k, f_ = (L[n][..., :3].astype(np.float64) / 65535 for n in ("light_key", "light_fill"))
d_add = (np.clip(k + f_, 0, 1) - b[..., :3])[op] * 255
d_lin = (enc(lin(k) + lin(f_)) - b[..., :3])[op] * 255
check(np.abs(d_lin).mean() < 1.0, f"light groups summed in linear light = the beauty: mean "
      f"{np.abs(d_lin).mean():.2f}, max {np.abs(d_lin).max():.1f} of 255 ({int(op.sum())} opaque px)")
both = op & (k.max(-1) > 0.02) & (f_.max(-1) > 0.02)
d_both = (np.clip(k + f_, 0, 1) - b[..., :3])[both] * 255
print(f"     Add on display values against the beauty: mean {d_add.mean():+.1f}, max {d_add.max():+.1f} of 255 "
      f"over opaque px; where both groups light the pixel ({int(both.sum())} px): mean {d_both.mean():+.1f}, "
      f"max {d_both.max():+.1f}")
scene.view_settings.view_transform = view_before
scene.cycles.use_denoising = denoise_before
s.denoise = True

check(bpy.ops.odv.post_preset(preset='MINIMAL') == {'FINISHED'} and g.nodes.get(po.AIDS_NODE) is None
      and g.nodes.get(po.LIGHT_NODE) is None and not any(n.name.startswith(po.HELPER_PREFIXES) for n in g.nodes)
      and [i.name for i in node.file_output_items] == ["matid"],
      "Minimal preset: extra File Output, Mix and Denoise nodes and the AOV item removed")
stem = render("minimal")
check(po.psd.read_summary(stem + ".psd")["layers"] == [("beauty", True, "norm"), ("matid", False, "norm")],
      "Minimal preset: PSD with beauty and matid only")
for o in ("Lamp", "Glass", "Key"):
    bpy.data.objects.remove(bpy.data.objects[o])
world.lightgroup = ""

# --- photo match: render over a photo with a shadow catcher -----------------------------

scene.odv_post.save_f12 = True
g = scene.compositing_node_group
group_out = next(n for n in g.nodes if n.bl_idname == "NodeGroupOutput")
rl0 = next(n for n in g.nodes if n.bl_idname == "CompositorNodeRLayers")
yy, xx = np.mgrid[0:90, 0:160]
v = np.where((xx // 20 + yy // 20) % 2 == 0, 0.95, 0.05).astype(np.float32)
photo_img = bpy.data.images.new("photo", 160, 90, alpha=False)
photo_img.pixels.foreach_set(np.stack([v, v, v, np.ones_like(v)], -1).ravel())
photo_img.update()
img_node = g.nodes.new("CompositorNodeImage")
img_node.image = photo_img
ao = g.nodes.new("CompositorNodeAlphaOver")
g.links.new(img_node.outputs["Image"], ao.inputs["Background"])
g.links.new(rl0.outputs["Image"], ao.inputs["Foreground"])
g.links.new(ao.outputs[0], group_out.inputs[0])
box("Ground", (0, -1, -1.1), (10, 10, 0.05), (0.5, 0.5, 0.5, 1))
bpy.data.objects["Ground"].is_shadow_catcher = True
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
sun.data.energy = 4.0
sun.rotation_euler = (0.6, 0.3, 0.8)
scene.collection.objects.link(sun)
bpy.ops.odv.matid_assign()
scene.camera = cams[0]
scene.view_settings.view_transform = 'Standard'   # a photo match keeps the photo as it is
scene.view_settings.look = 'None'

check(bpy.ops.odv.post_setup() == {'FINISHED'} and bpy.ops.odv.post_setup() == {'FINISHED'}, "photo match: Set up (twice)")
mult = g.nodes.get(po.MULTIPLY_NODE)
lay = g.nodes.get(po.LAYERS_NODE)
check(scene.view_layers[0].cycles.use_pass_shadow_catcher, "photo match: Shadow Catcher pass on")
check(mult is not None and ao.inputs["Background"].links[0].from_node == mult
      and po._socket(mult.inputs, "A_Color").links[0].from_node == img_node
      and po._socket(mult.inputs, "B_Color").links[0].from_socket.name == "Shadow Catcher"
      and mult.blend_type == 'MULTIPLY',
      "photo match: photo x Shadow Catcher multiplied before the Alpha Over")
check(lay is not None and [i.name for i in lay.file_output_items] == ["render", "photo"]
      and lay.format.color_mode == 'RGBA' and lay.format.color_management == 'FOLLOW_SCENE',
      "photo match: render and photo File Output, RGBA, scene view transform")
check([i.name for i in node.file_output_items] == ["matid", "shadow"], "photo match: shadow written with the Standard view")
check(sum(1 for n in g.nodes if n.name.startswith("odv_")) == 3, "photo match: Set up twice adds no extra nodes")


# Photographer's render queue keeps references to File Output items in a list on
# its operator class and renames them on its next run; a removed item crashes
# Blender. A stand-in with the same bl_idname and list:
class RENDER_OT_renderqueue(bpy.types.Operator):
    bl_idname = "render.renderqueue"
    bl_label = "stand-in for Photographer's render queue"
    file_outputs = []


bpy.utils.register_class(RENDER_OT_renderqueue)
ptrs = [i.as_pointer() for n in (node, lay) for i in n.file_output_items]
RENDER_OT_renderqueue.file_outputs.extend((i, i.name) for n in (node, lay) for i in n.file_output_items)
bpy.ops.odv.post_setup()
check([i.as_pointer() for n in (node, lay) for i in n.file_output_items] == ptrs
      and len(RENDER_OT_renderqueue.file_outputs) == 4,
      "Set up again keeps the same File Output items (and leaves the queue's list alone)")

# Black boxes bounce no light onto the shadow catcher. Cycles adds such light to the
# Combined pass as colour at alpha 0, which a straight-alpha layer cannot carry
# (measured below with the coloured boxes); without it, photo x shadow can be
# compared with Blender's composite directly.
colours = {m.name: tuple(m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value) for m in (wall, brick)}
for m in (wall, brick):
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0, 0, 0, 1)
stem = render("pm")
want = [("photo", True, "norm"), ("shadow", True, "mul "), ("render", True, "norm"),
        ("composite", False, "norm"), ("matid", False, "norm")]
ok = os.path.exists(stem + ".psd")
check(ok and po.psd.read_summary(stem + ".psd")["layers"] == want,
      "photo match: PSD layers matid, composite (hidden), render, shadow (Multiply), photo")
if ok:
    layers, composite, _ = read_psd(stem + ".psd")
    f = {k: raw(stem + ("" if k == "composite" else "_" + k) + ".png") for k in ("render", "photo", "shadow", "composite")}
    check(all(np.array_equal(layers[k][..., :3], f[k][..., :3]) for k in f)
          and np.array_equal(layers["render"][..., 3], f["render"][..., 3]),
          "photo match: render, photo, shadow and composite layers = their PNG files, bit-exact")
    check(f["shadow"][..., :3].min() < 0.8 * 65535, "photo match: the shadow pass has shadows")
    stack = po._stack(f["photo"], f["shadow"], f["render"])
    check(np.array_equal(composite, po.psd.flatten_over_white(stack)), "photo match: PSD composite = the visible stack")
    a = f["render"][..., 3]
    diff = (stack[..., :3].astype(int) - f["composite"][..., :3].astype(int)) / 257
    d = np.abs(diff).max(-1)
    shadowed = (a == 0) & (f["shadow"][..., :3].min(-1) < 0.95 * 65535)
    # sRGB is not a pure power curve, so Multiply on display values is close to, not
    # exactly, the linear multiply; 16 samples add noise between the passes.
    check(shadowed.sum() > 100 and d[shadowed].max() <= 5,
          f"photo match: in the shadows, photo x shadow matches Blender's composite within "
          f"{d[shadowed].max():.1f} of 255, mean {d[shadowed].mean():.2f} ({int(shadowed.sum())} px)")
    print(f"     at partially transparent render pixels: max {d[(a > 0) & (a < 65535)].max():.1f}, "
          f"mean {d[(a > 0) & (a < 65535)].mean():.1f} of 255 (Normal blend on display values)")


for m in (wall, brick):
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = colours[m.name]
stem = render("pm_colour")
f2 = {k: raw(stem + ("" if k == "composite" else "_" + k) + ".png") for k in ("render", "photo", "shadow", "composite")}
diff2 = (po._stack(f2["photo"], f2["shadow"], f2["render"])[..., :3].astype(int) - f2["composite"][..., :3].astype(int)) / 257
a2 = f2["render"][..., 3]
lost = (a2 == 0) & (diff2.min(-1) < -3)
print(f"     coloured boxes: light that Cycles adds onto the shadow catcher (colour at alpha 0) is not "
      f"carried: {int(lost.sum())} of {int((a2 == 0).sum())} transparent px darker than Blender by > 3 of 255, "
      f"max {float((-diff2.min(-1))[a2 == 0].max()):.1f}")

bpy.data.objects["Ground"].is_shadow_catcher = False
bpy.ops.odv.post_setup()
check(g.nodes.get(po.MULTIPLY_NODE) is None and ao.inputs["Background"].links[0].from_node == img_node
      and [i.name for i in node.file_output_items] == ["matid"],
      "photo match without shadow catchers: multiply removed, photo linked back")
check(RENDER_OT_renderqueue.file_outputs == [],
      "an item removed by Set up: the render queue's list of items is emptied")
bpy.utils.unregister_class(RENDER_OT_renderqueue)
stem = render("pm_noshadow")
check(po.psd.read_summary(stem + ".psd")["layers"] == [l for l in want if l[0] != "shadow"],
      "photo match without shadow catchers: PSD without the shadow layer")

# Photo match preset in a photo match: AO is added; the shadow catcher, which the
# photo match delivers as its shadow layer already, does not get a second layer.
bpy.data.objects["Ground"].is_shadow_catcher = True
check(bpy.ops.odv.post_preset(preset='PHOTO') == {'FINISHED'}
      and [i.name for i in node.file_output_items] == ["matid", "shadow"]
      and [i.name for i in g.nodes[po.AIDS_NODE].file_output_items] == ["ao"],
      "Photo match preset in a photo match: AO set up, shadow once")
stem = render("pm_preset")
check(po.psd.read_summary(stem + ".psd")["layers"]
      == [("photo", True, "norm"), ("shadow", True, "mul "), ("render", True, "norm"),
          ("composite", False, "norm"), ("ao", False, "mul "), ("matid", False, "norm")],
      "Photo match preset: photo, shadow, render, composite, ao (hidden, Multiply), matid; one layer per role")

# --- unregister ----------------------------------------------------------------------

odv_tools.unregister()
check(not hasattr(bpy.types.Scene, "odv_post") and not hasattr(bpy.types, "ODV_OT_post_setup")
      and po._on_render_pre not in bpy.app.handlers.render_pre and not bpy.app.timers.is_registered(po._tick),
      "unregister: no settings, operators, handlers or timer left")

print(f"\n{len(FAILED)} failed" if FAILED else "\nall checks passed")
sys.exit(1 if FAILED else 0)
