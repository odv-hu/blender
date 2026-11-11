"""Post-production output: per camera, a final-look 16-bit beauty, the
material ID as a file and both as one layered PSD (#20, #21).

*Set up* points the scene's output at a 16-bit PNG with alpha (view transform
applied) and adds a File Output node that writes the Material ID AOV with the
Standard view, so its colours are exact. After each render the handlers
write `<beauty>.psd` next to the beauty: `matid` on top (hidden) and `beauty`
below (visible, alpha as layer transparency).

In a photo-match scene, where the compositor lays the render over a photo with
an Alpha Over node, the PSD keeps them apart instead: `render` (alpha as
transparency) over `shadow` (the Shadow Catcher pass, Multiply) over `photo`,
with Blender's own result as a hidden `composite` layer. Set-up switches the
Shadow Catcher pass on and multiplies the photo by it in the compositor, the
way Cycles intends, because with the pass on the Combined pass no longer
carries the shadows. Multiply on display values gives almost exactly the
linear result, so the shadows look as in Blender; Normal blending on display
values does not, which is why the shadows are not left in the render layer.

Extra passes (#22) are post-production aids, ticked in the panel or set by a
preset: mist and AO (written with the Raw view, stretched to black-white per
image when read), light groups, reflection, refraction, emission, environment
and albedo (scene view transform; light groups and light passes denoised in the
compositor), and the view layer's own AOVs (Standard view, exact). Each becomes
one hidden layer with its blend mode. A pass the PSD already has for another
reason (render, shadow, photo, matid) never gets a second layer.

The PSD is written when Blender writes the render (a render queue such as
Photographer's, or a command-line render) and, with *Save F12 renders*, after
F12: the render result is saved to the output path first. Render handlers run
on the render thread in the interactive Blender, so they only note the file
names; a timer picks the job up on the main thread, and a worker thread reads
the files and writes the PSD so that the interface and a running queue do not
wait for it.
"""

import os
import queue
import shutil
import threading
import time
import traceback

import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ExportHelper

from . import psd
from ..material_id import AOV_NAME

NODE_NAME = "odv_matid"       # File Output, Standard view, 16-bit RGB: matid, shadow, aov_<name>
LAYERS_NODE = "odv_layers"    # File Output, scene view transform, 16-bit RGBA: render, photo
AIDS_NODE = "odv_aids"        # File Output, Raw view, 16-bit RGB: mist, ao (stretched when read)
LIGHT_NODE = "odv_light"      # File Output, scene view transform, 16-bit RGB: light groups and passes
OUTPUT_NODES = (NODE_NAME, LAYERS_NODE, AIDS_NODE, LIGHT_NODE)
MULTIPLY_NODE = "odv_shadow_multiply"
HELPER_PREFIXES = ("odv_mix_", "odv_dn_")   # Mix and Denoise nodes of the extra passes
ITEM_NAME = "matid"
ROLES = ("matid", "shadow", "render", "photo")   # file <beauty>_<role>.png
ROLES_PROP = "odv_roles"      # on our File Output nodes: the roles of their items, in order

# Extra passes (#22), all delivered as hidden layers. key: (label, tooltip)
PASSES = {
    "mist": ("Mist", "Cycles Mist pass (distance from the camera), greyscale, stretched to "
                     "black-white per image. Screen layer"),
    "ao": ("AO", "Ambient Occlusion pass, greyscale, stretched to black-white per image. Multiply layer"),
    "lightgroups": ("Light groups", "One layer per light group of the view layer, scene view transform. "
                                    "Linear Dodge (Add) layers"),
    "reflection": ("Reflection", "Glossy direct + indirect, times glossy colour, scene view transform. "
                                 "Linear Dodge (Add) layer"),
    "refraction": ("Refraction", "Transmission direct + indirect, times transmission colour, scene view "
                                 "transform. Linear Dodge (Add) layer"),
    "emission": ("Emission", "Emission pass, scene view transform. Linear Dodge (Add) layer"),
    "environment": ("Environment", "Environment pass (the world where it is seen directly), scene view "
                                   "transform. Linear Dodge (Add) layer"),
    "albedo": ("Albedo", "Diffuse Color pass, scene view transform. Normal layer"),
    "aovs": ("Custom AOVs", "Every AOV of the view layer except the material ID, exact values "
                            "(Standard view). Normal layers"),
}
# key: (label, tooltip, ticked passes)
PRESETS = {
    "MINIMAL": ("Minimal", "No extra passes: beauty and material ID (render, shadow and photo in a "
                           "photo match)", ()),
    "PHOTO": ("Photo match", "Minimal and AO. A photo match delivers the shadow catcher as its shadow "
                             "layer already", ("ao",)),
    "FULL": ("Full", "Every extra pass except environment and albedo",
             ("mist", "ao", "lightgroups", "reflection", "refraction", "emission", "aovs")),
}
GREY_ROLES = ("mist", "ao")
ADD_ROLES = ("reflection", "refraction", "emission", "environment")
SIMPLE_SOURCES = {"mist": "Mist", "ao": "Ambient Occlusion", "emission": "Emission",
                  "environment": "Environment", "albedo": "Diffuse Color"}
LIGHT_SUMS = {"reflection": "Glossy", "refraction": "Transmission"}
GEOMETRY = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME'}
LAYERS_NODE_NAME = "odv Render Layers"
POLL_S = 0.5
MAX = 65535


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

class ODV_PG_post_output(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Layered PSD",
        default=False,
        description="After each render, write <beauty>.psd next to the beauty, with the "
                    "beauty and the material ID as layers. Switched on by Set up")
    keep_separate: bpy.props.BoolProperty(
        name="Keep separate files",
        default=True,
        description="Keep the beauty PNG and the ID PNG next to the PSD. When off, they are "
                    "deleted after the PSD has been written and read back")
    save_f12: bpy.props.BoolProperty(
        name="Save F12 renders",
        default=True,
        description="After an F12 render, save the beauty to the output path and write the PSD. "
                    "When off, use Image › Save Layered PSD... in the Image Editor")
    denoise: bpy.props.BoolProperty(
        name="Denoise light passes",
        default=True,
        description="A compositor Denoise node for each light group and for reflection and "
                    "refraction: Cycles denoises only the Combined pass")


for _key, (_label, _tip) in PASSES.items():
    ODV_PG_post_output.__annotations__["pass_" + _key] = bpy.props.BoolProperty(
        name=_label, default=False, description=_tip)


def settings(scene):
    return getattr(scene, "odv_post", None)


def ticked(s):
    """The extra passes ticked in the panel, in PASSES order."""
    return [k for k in PASSES if s is not None and getattr(s, "pass_" + k, False)]


def pass_roles(view_layer, s):
    """{output node name: [roles]} of the ticked extra passes on this view layer."""
    keys = ticked(s)
    out = {NODE_NAME: [], AIDS_NODE: [k for k in GREY_ROLES if k in keys], LIGHT_NODE: []}
    if "aovs" in keys:
        out[NODE_NAME] = ["aov_" + a.name for a in view_layer.aovs if a.name != AOV_NAME]
    if "lightgroups" in keys:
        out[LIGHT_NODE] = ["light_" + lg.name for lg in view_layer.lightgroups]
    out[LIGHT_NODE] += [k for k in ADD_ROLES + ("albedo",) if k in keys]
    return out


# ---------------------------------------------------------------------------
# file names
# ---------------------------------------------------------------------------

def _extension(scene):
    return os.path.splitext(scene.render.frame_path(frame=scene.frame_current))[1]


def beauty_candidates(scene):
    """Where Blender writes the beauty of this render.

    Blender 5.3 writes a still to the output path as typed, plus the extension,
    without a frame number; frames of an animation get one (frame_path).
    """
    r = scene.render
    path = bpy.path.abspath(r.filepath)
    ext = _extension(scene)
    if r.use_file_extension and ext and not path.lower().endswith(ext.lower()):
        path += ext
    return [os.path.normpath(path),
            os.path.normpath(r.frame_path(frame=scene.frame_current))]


def id_node(scene):
    g = scene.compositing_node_group
    n = g.nodes.get(NODE_NAME) if g else None
    return n if n and n.bl_idname == "CompositorNodeOutputFile" else None


def _role(item_name, names=ROLES):
    """The role of a File Output item among `names`; a render queue may prefix the
    item names. The longest match wins (light_key_sun before light_sun)."""
    for role in sorted(names, key=len, reverse=True):
        if item_name == role or item_name.endswith("_" + role):
            return role
    return None


def _node_roles(node):
    """The roles of an output node's items, as set up; ROLES for a node set up by 0.0.5."""
    names = node.get(ROLES_PROP)
    return [str(n) for n in names] if names else list(ROLES)


def item_files(scene):
    """{role: file} that our File Output nodes write in this render: directory +
    file name + item name. Photographer renames the items for each camera."""
    out = {}
    g = scene.compositing_node_group
    if g is None or not scene.render.use_compositing:
        return out
    for node_name in OUTPUT_NODES:
        node = g.nodes.get(node_name)
        if node is None or node.bl_idname != "CompositorNodeOutputFile" or node.mute:
            continue
        directory = bpy.path.abspath(node.directory)
        names = _node_roles(node)
        for i, item in enumerate(node.file_output_items):
            role = _role(item.name, names)
            if role is None or not node.inputs[i].is_linked:
                continue
            name = node.file_name + item.name
            # use_file_extension is new in Blender 5.2; 5.0 and 5.1 always add the extension.
            if getattr(node, "use_file_extension", True) and node.format.file_format == 'PNG':
                name += ".png"
            out[role] = os.path.normpath(os.path.join(directory, name))
    return out


def _socket(sockets, identifier):
    return next(s for s in sockets if s.identifier == identifier)


def photo_match(g):
    """(Alpha Over node, Render Layers node, photo socket) when the compositor lays
    the render over a photo just before the output, else None."""
    if g is None:
        return None
    for ao in g.nodes:
        if ao.bl_idname != "CompositorNodeAlphaOver" or ao.mute:
            continue
        if not any(l.to_node.bl_idname == "NodeGroupOutput" for l in ao.outputs[0].links):
            continue
        fg, bg = ao.inputs["Foreground"], ao.inputs["Background"]
        if not (fg.is_linked and bg.is_linked):
            continue
        rl = fg.links[0].from_node
        if rl.bl_idname != "CompositorNodeRLayers":
            continue
        photo = bg.links[0].from_socket
        if photo.node.name == MULTIPLY_NODE:
            a = _socket(photo.node.inputs, "A_Color")
            if not a.is_linked:
                continue
            photo = a.links[0].from_socket
        return ao, rl, photo
    return None


def output_problem(path):
    """A reason why the beauty cannot be saved to `path`, or None."""
    if not path or path.startswith("//"):
        return "the output path is relative and the .blend file is not saved"
    if not os.path.basename(os.path.splitext(path)[0]):
        return "the output path has no file name"
    return None


# ---------------------------------------------------------------------------
# reading images
# ---------------------------------------------------------------------------

def _straight(px):
    """Premultiplied RGBA uint16 -> straight, in place."""
    a = px[..., 3:].astype(np.float32)
    rgb = px[..., :3].astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(a > 0, rgb * MAX / a, 0.0)
    px[..., :3] = np.round(np.clip(s, 0, MAX)).astype(np.uint16)
    return px


def read_image(path):
    """Read an image as uint16 RGBA with straight alpha, as stored (no colour
    conversion). Returns (pixels, icc bytes or None)."""
    import OpenImageIO as oiio
    cfg = oiio.ImageSpec()
    cfg.attribute("oiio:UnassociatedAlpha", 1)   # do not premultiply on read
    inp = oiio.ImageInput.open(path, cfg)
    if inp is None:
        raise OSError(f"cannot open {os.path.basename(path)}: {oiio.geterror()}")
    try:
        spec = inp.spec()
        px = inp.read_image(0, 0, 0, spec.nchannels, oiio.UINT16)
        icc = spec.getattribute("ICCProfile")
        unassociated = spec.get_int_attribute("oiio:UnassociatedAlpha", 0)
        alpha = spec.alpha_channel
    finally:
        inp.close()
    if px is None:
        raise OSError(f"cannot read {os.path.basename(path)}: {oiio.geterror()}")
    n = spec.nchannels
    px = np.asarray(px).reshape(spec.height, spec.width, n)
    out = np.full((spec.height, spec.width, 4), MAX, np.uint16)
    if n < 3:
        out[..., :3] = px[..., :1]
        if n == 2:
            out[..., 3] = px[..., 1]
    else:
        out[..., :3] = px[..., :3]
        if n >= 4:
            out[..., 3] = px[..., 3]
            # Without the flag the file stores premultiplied colour (Blender's TIFF does).
            if alpha == 3 and not unassociated:
                _straight(out)
    if icc is not None:
        icc = bytes(np.asarray(icc, dtype=np.uint8))
    return out, icc


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_pending = {}               # scene name -> job, from render_pre to render_complete
_done = queue.Queue()       # finished renders, for the main thread
_work = queue.Queue()       # PSDs to write, for the worker thread
_messages = queue.Queue()   # (level, text), reported on the main thread
_last = {"job": None, "status": ""}
_worker = None


def _say(level, text):
    print(f"odv post-production output: {text}")
    _messages.put((level, text))


def _fresh(path, start):
    return bool(path) and os.path.exists(path) and os.path.getmtime(path) >= start - 1


def _stack(photo, shadow, render):
    """What the editor shows: photo, multiplied by the shadow, render over it (Normal,
    straight alpha, on display values). uint16 RGBA."""
    base = photo.astype(np.float32) / MAX
    if shadow is not None:
        base[..., :3] *= shadow[..., :3].astype(np.float32) / MAX
    top = render.astype(np.float32) / MAX
    a, ab = top[..., 3:], base[..., 3:]
    out_a = a + ab * (1 - a)
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb = np.where(out_a > 0, (top[..., :3] * a + base[..., :3] * ab * (1 - a)) / out_a, 0.0)
    out = np.concatenate([rgb, out_a], -1)
    return np.round(np.clip(out, 0, 1) * MAX).astype(np.uint16)


def _stretch(img):
    """A greyscale aid stretched to the full black-white range of this image, as RGB."""
    v = img[..., 0]
    lo, hi = int(v.min()), int(v.max())
    if hi > lo:
        v = np.round((v.astype(np.float64) - lo) * (MAX / (hi - lo))).astype(np.uint16)
    return np.repeat(v[..., None], 3, -1)


def _aid_spec(role):
    """(rank, blend) of an extra pass in the PSD, bottom first; None for other roles."""
    if role == "albedo":
        return 0, b"norm"
    if role.startswith("light_") or role in ADD_ROLES:
        return 1, b"lddg"
    if role == "ao":
        return 2, b"mul "
    if role == "mist":
        return 3, b"scrn"
    if role.startswith("aov_"):
        return 4, b"norm"
    return None


def _aid_layers(px):
    """Hidden layers of the extra passes, bottom first: albedo, light groups and light
    passes (Add), AO (Multiply), mist (Screen), custom AOVs. Within a rank, in the
    order of the File Output items."""
    found = [(spec, role) for role in px if (spec := _aid_spec(role))]
    found.sort(key=lambda t: t[0][0])
    return [psd.Layer(role, _stretch(px[role]) if role in GREY_ROLES else px[role][..., :3],
                      False, spec[1]) for spec, role in found]


def _write(job):
    """Read the beauty and the pass files, write and check the PSD, tidy up. Any thread."""
    t = time.perf_counter()
    beauty = job["beauty_file"]
    tmp = None
    try:
        rgba, icc = read_image(beauty)
        px, used = {}, {}
        for role, path in job["items"].items():
            if not _fresh(path, job["start"]):
                continue
            img, _ = read_image(path)
            if img.shape[:2] != rgba.shape[:2]:
                _say('WARNING', f"{os.path.basename(path)} has another size than the beauty; left out of the PSD")
                continue
            px[role], used[role] = img, path

        if "render" in px and "photo" not in px:
            _say('WARNING', "photo match, but no photo file from this render (is the photo image found?); "
                            "PSD written with Blender's result as the beauty layer")
        if "render" in px and "photo" in px:
            layers = [psd.Layer("photo", px["photo"], True, b"norm")]
            if "shadow" in px:
                layers.append(psd.Layer("shadow", px["shadow"][..., :3], True, b"mul "))
            layers += [psd.Layer("render", px["render"], True, b"norm"),
                       psd.Layer("composite", rgba, False, b"norm")]
            composite = psd.flatten_over_white(_stack(px["photo"], px.get("shadow"), px["render"]))
        else:
            layers = [psd.Layer("beauty", rgba, True, b"norm")]
            composite = psd.flatten_over_white(rgba)
        layers += _aid_layers(px)
        if "matid" in px:
            layers.append(psd.Layer("matid", px["matid"][..., :3], False, b"norm"))
        else:
            _say('WARNING', "no ID file from this render (Material ID not assigned, node muted "
                            "or compositing off); PSD written without the material ID")

        stem = os.path.splitext(beauty)[0]
        out = stem + ".psd"
        tmp = out + ".part"
        psd.write(tmp, layers, composite, icc=icc)
        summary = psd.read_summary(tmp)
        # The Pascal name in the layer record is ASCII; the Unicode name is stored as well.
        expected = [(l.name.encode("ascii", "replace")[:255].decode("ascii"), l.visible,
                     l.blend.decode("ascii")) for l in layers]
        if summary["layers"] != expected or summary["depth"] != 16 \
                or (summary["height"], summary["width"]) != rgba.shape[:2]:
            raise ValueError(f"read-back check failed: {summary}")
        os.replace(tmp, out)
        tmp = None
        size = os.path.getsize(out) / 1e6
        names = ", ".join(l.name for l in reversed(layers))
        _say('INFO', f"{os.path.basename(out)} written ({names}): "
                     f"{size:.0f} MB, {time.perf_counter() - t:.1f} s")
    except Exception as e:
        traceback.print_exc()
        _say('ERROR', f"layered PSD not written for {os.path.basename(beauty)}: {e}. "
                      "The separate files are kept")
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return

    # Tidy up the separate files. The File Output nodes may write to another
    # drive than the beauty, so move with shutil (copies when it has to). Once
    # they sit next to a PSD, a later save of the same render (Save Layered PSD
    # to another name) copies them, so that the first PSD keeps its files.
    try:
        if job["keep"]:
            for role, path in used.items():
                target = f"{stem}_{role}.png"
                if os.path.normcase(path) == os.path.normcase(target):
                    continue
                if job.get("tidied"):
                    shutil.copy2(path, target)
                else:
                    shutil.move(path, target)
                    job["items"][role] = target
            job["tidied"] = True
        else:
            os.remove(beauty)
            for path in used.values():
                os.remove(path)
    except Exception as e:
        traceback.print_exc()
        _say('WARNING', f"{os.path.basename(out)} written, but the separate files could not be "
                        f"moved or deleted: {e}")


def _worker_loop():
    while True:
        job = _work.get()
        if job is None:
            return
        _write(job)


def _queue_write(job):
    global _worker
    if bpy.app.background:
        _write(job)
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_worker_loop, name="odv_post_output", daemon=True)
        _worker.start()
    _work.put(job)


def start(job, save=False):
    """Main thread: save the F12 render if needed, then queue the PSD."""
    _last["job"] = job
    if job["written"]:
        files = [p for p in job["beauty"] if os.path.exists(p)
                 and os.path.getmtime(p) >= job["start"] - 1]
        if not files:
            _say('ERROR', f"the written beauty was not found (looked for {os.path.basename(job['beauty'][0])})")
            return False
        job["beauty_file"] = files[0]
    else:
        if not (save or job["save_f12"]):
            return False
        scene = bpy.data.scenes.get(job["scene"])
        rr = bpy.data.images.get("Render Result")
        path = job["beauty"][0]
        problem = output_problem(path) or (scene is None and "the scene is gone") \
            or (rr is None and "there is no render result")
        if problem:
            _say('WARNING', f"render not saved: {problem}")
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rr.save_render(path, scene=scene)
        job["beauty_file"] = path
        job["written"] = True
    _queue_write(job)
    return True


@persistent
def _on_render_pre(scene, *args):
    s = settings(scene)
    if s is None or not s.enabled:
        return
    try:
        job = {"scene": scene.name, "start": time.time(), "written": False,
               "beauty": beauty_candidates(scene), "items": item_files(scene),
               "keep": s.keep_separate, "save_f12": s.save_f12}
    except Exception as e:   # never break a render
        print(f"odv post-production output: {e}")
        job = None
    with _lock:
        _pending[scene.name] = job


@persistent
def _on_render_write(scene, *args):
    with _lock:
        job = _pending.get(scene.name)
        if job:
            job["written"] = True


@persistent
def _on_render_complete(scene, *args):
    with _lock:
        job = _pending.pop(scene.name, None)
    if not job:
        return
    if bpy.app.background:
        start(job)          # main thread already, and no timers run
    else:
        _done.put(job)


@persistent
def _on_render_cancel(scene, *args):
    with _lock:
        _pending.pop(scene.name, None)


def _tick():
    while True:
        try:
            job = _done.get_nowait()
        except queue.Empty:
            break
        try:
            start(job)
        except Exception as e:
            traceback.print_exc()
            _say('ERROR', f"render not saved: {e}")
    while True:
        try:
            level, text = _messages.get_nowait()
        except queue.Empty:
            break
        _last["status"] = text
        _report(level, text)
    return POLL_S


def _report(level, text):
    wm = bpy.context.window_manager
    if not wm or not wm.windows:
        return
    try:
        with bpy.context.temp_override(window=wm.windows[0]):
            bpy.ops.odv.post_report(level=level, message=text)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# set-up
# ---------------------------------------------------------------------------

def _compositor_group(scene):
    g = scene.compositing_node_group
    if g is None:
        g = bpy.data.node_groups.new(f"odv compositor {scene.name}", "CompositorNodeTree")
        g.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
        rl = g.nodes.new("CompositorNodeRLayers")
        rl.scene = scene
        out = g.nodes.new("NodeGroupOutput")
        out.location = (400, 0)
        g.links.new(rl.outputs["Image"], out.inputs[0])
        scene.compositing_node_group = g
    return g


def _forget_queue_items():
    """Empty the File Output items that Photographer's render queue keeps.

    Its operator keeps them in a list on the class, adds to it on every run and
    never empties it; on the next run it renames every item in it. An item that
    has been removed since makes Blender crash (seen with Photographer 5.8.4 on
    Blender 5.3). Called whenever set-up removes an item or a node.
    """
    queue_op = getattr(bpy.types, "RENDER_OT_renderqueue", None)
    items = getattr(queue_op, "file_outputs", None)
    if isinstance(items, list):
        items.clear()


def _set_items(node, names):
    """Make the node's items exactly `names`, in order, keeping the items that are
    already there (a render queue may hold references to them). Returns True if an
    item was removed."""
    items = node.file_output_items
    removed = False
    for item in list(items):
        role = _role(item.name, names)
        if role in names and item.name != role:
            item.name = role          # a queue that stopped half-way left its name on it
        elif role not in names:
            items.remove(item)
            removed = True
    have = [item.name for item in items]
    for name in names:
        if name not in have:
            items.new('RGBA', name)
    for target, name in enumerate(names):
        current = [item.name for item in items].index(name)
        if current != target:
            items.move(current, target)
    node[ROLES_PROP] = list(names)
    return removed


def _file_output(g, name, label, location):
    node = g.nodes.get(name)
    if node is None or node.bl_idname != "CompositorNodeOutputFile":
        node = g.nodes.new("CompositorNodeOutputFile")
        node.name = name
        node.location = location
    node.label = label
    node.file_name = ""
    node.mute = False
    f = node.format
    f.media_type = 'IMAGE'
    f.file_format = 'PNG'
    f.color_depth = '16'
    return node


def _standard_view(node, scene, view='Standard'):
    """Write values without the scene's look. Standard: exact ID colours, a shadow
    factor that multiplies correctly on display values. Raw: linear values, for the
    greyscale aids that are stretched after reading."""
    node.format.color_management = 'OVERRIDE'
    node.format.display_settings.display_device = scene.display_settings.display_device
    vs = node.format.view_settings
    vs.view_transform = view
    vs.look = 'None'
    vs.exposure = 0.0
    vs.gamma = 1.0
    vs.use_curve_mapping = False
    node.save_as_render = True


def _shadow_multiply(g, ao, rl, photo):
    """photo x Shadow Catcher pass -> Alpha Over background, in the compositor."""
    m = g.nodes.get(MULTIPLY_NODE)
    if m is None or m.bl_idname != "ShaderNodeMix":
        m = g.nodes.new("ShaderNodeMix")
        m.name = MULTIPLY_NODE
        m.location = (ao.location.x - 200, ao.location.y - 150)
    m.label = "Shadow catcher (odv)"
    m.data_type = 'RGBA'
    m.blend_type = 'MULTIPLY'
    m.clamp_result = False
    _socket(m.inputs, "Factor_Float").default_value = 1.0
    g.links.new(photo, _socket(m.inputs, "A_Color"))
    g.links.new(rl.outputs["Shadow Catcher"], _socket(m.inputs, "B_Color"))
    g.links.new(_socket(m.outputs, "Result_Color"), ao.inputs["Background"])


def _helper(g, name, idname, keep, location):
    """A Mix or Denoise node of the extra passes, created once and marked as in use."""
    n = g.nodes.get(name)
    if n is not None and n.bl_idname != idname:
        g.nodes.remove(n)
        n = None
    if n is None:
        n = g.nodes.new(idname)
        n.name = name
        n.location = location
    keep.add(name)
    return n


def _mix(g, name, blend, a, b, keep, location):
    m = _helper(g, name, "ShaderNodeMix", keep, location)
    m.data_type = 'RGBA'
    m.blend_type = blend
    m.clamp_result = False
    _socket(m.inputs, "Factor_Float").default_value = 1.0
    g.links.new(a, _socket(m.inputs, "A_Color"))
    g.links.new(b, _socket(m.inputs, "B_Color"))
    return _socket(m.outputs, "Result_Color")


def _enable_cycles_passes(view_layer, keys):
    vl = view_layer
    if "mist" in keys:
        vl.use_pass_mist = True
    if "ao" in keys:
        vl.use_pass_ambient_occlusion = True
    if "reflection" in keys:
        vl.use_pass_glossy_direct = vl.use_pass_glossy_indirect = vl.use_pass_glossy_color = True
    if "refraction" in keys:
        vl.use_pass_transmission_direct = vl.use_pass_transmission_indirect = True
        vl.use_pass_transmission_color = True
    if "emission" in keys:
        vl.use_pass_emit = True
    if "environment" in keys:
        vl.use_pass_environment = True
    if "albedo" in keys:
        vl.use_pass_diffuse_color = True


# Render Layers output names as in Blender 5.3, and the short pass names that
# other Blender versions may use for the same output.
SHORT_NAMES = {"Ambient Occlusion": "AO", "Diffuse Color": "DiffCol", "Emission": "Emit",
               "Environment": "Env", "Glossy Direct": "GlossDir", "Glossy Indirect": "GlossInd",
               "Glossy Color": "GlossCol", "Transmission Direct": "TransDir",
               "Transmission Indirect": "TransInd", "Transmission Color": "TransCol"}


def _output(rl, name):
    """A Render Layers output by its 5.3 name or its short pass name."""
    for n in (name, SHORT_NAMES.get(name)):
        if n and n in rl.outputs:
            return rl.outputs[n]
    raise KeyError(f"the Render Layers node has no output {name!r}")


def _pass_socket(g, rl, role, keep, location):
    """The compositor socket that carries an extra pass."""
    if role in SIMPLE_SOURCES:
        return _output(rl, SIMPLE_SOURCES[role])
    if role.startswith("light_"):
        return _output(rl, "Combined_" + role[len("light_"):])
    if role.startswith("aov_"):
        return _output(rl, role[len("aov_"):])
    base = LIGHT_SUMS[role]       # (direct + indirect) x colour, as Cycles composes it
    x, y = location
    s = _mix(g, f"odv_mix_{role}_add", 'ADD', _output(rl, base + " Direct"),
             _output(rl, base + " Indirect"), keep, (x, y))
    return _mix(g, f"odv_mix_{role}_colour", 'MULTIPLY', s, _output(rl, base + " Color"),
                keep, (x + 180, y))


def _setup_passes(g, scene, view_layer, rl, fo, roles, directory, denoise):
    """File Output nodes, Mix and Denoise nodes and Cycles passes for the ticked extra
    passes; removes those no longer ticked. Returns True if a File Output item or
    node was removed."""
    _enable_cycles_passes(view_layer, ticked(settings(scene)))
    removed, keep = False, set()
    x, y = rl.location.x + 300, rl.location.y - 300
    for node_name, label, view in ((AIDS_NODE, "Mist and AO files (odv)", 'Raw'),
                                   (LIGHT_NODE, "Light pass files (odv)", None)):
        names = roles[node_name]
        node = g.nodes.get(node_name)
        if not names:
            if node is not None:
                g.nodes.remove(node)
                removed = True
            continue
        node = _file_output(g, node_name, label, (x + 600, y))
        node.directory = directory
        node.format.color_mode = 'RGB'
        if view:
            _standard_view(node, scene, view)
        else:
            node.format.color_management = 'FOLLOW_SCENE'
            node.save_as_render = True
        if _set_items(node, names):
            removed = True
        for role in names:
            sock = _pass_socket(g, rl, role, keep, (x, y))
            if denoise and (role.startswith("light_") or role in LIGHT_SUMS):
                dn = _helper(g, "odv_dn_" + role, "CompositorNodeDenoise", keep, (x + 380, y))
                dn.label = f"Denoise {role} (odv)"
                if "HDR" in dn.inputs:
                    dn.inputs["HDR"].default_value = True
                g.links.new(sock, dn.inputs["Image"])
                sock = dn.outputs["Image"]
            g.links.new(sock, node.inputs[role])
            y -= 160
    for role in roles[NODE_NAME]:
        g.links.new(_pass_socket(g, rl, role, keep, (x, y)), fo.inputs[role])
    for n in list(g.nodes):
        if n.name.startswith(HELPER_PREFIXES) and n.name not in keep:
            g.nodes.remove(n)
    return removed


def _passes_note(view_layer, s, roles):
    """The extra passes for the set-up message."""
    keys = ticked(s)
    if not keys:
        return ""
    names = [r for rs in roles.values() for r in rs]
    note = f". Extra passes as hidden layers: {', '.join(names) or 'none'}"
    if "lightgroups" in keys and not view_layer.lightgroups:
        note += ". Light groups ticked, but the view layer has none"
    if "aovs" in keys and not roles[NODE_NAME]:
        note += ". Custom AOVs ticked, but the view layer has none besides the material ID"
    return note


def setup(scene, view_layer):
    """Set the scene up for post-production output. Returns (level, message)."""
    r = scene.render
    im = r.image_settings
    im.media_type = 'IMAGE'
    im.file_format = 'PNG'
    im.color_depth = '16'
    im.color_mode = 'RGBA'
    im.color_management = 'FOLLOW_SCENE'
    r.use_compositing = True
    settings(scene).enabled = True

    if AOV_NAME not in view_layer.aovs:
        return ('WARNING', "Output set to 16-bit PNG and the layered PSD switched on, but the "
                           f"view layer has no {AOV_NAME} AOV: run Assign material IDs, then Set up again")

    g = _compositor_group(scene)
    rl = next((n for n in g.nodes if n.bl_idname == "CompositorNodeRLayers"
               and n.scene in (None, scene) and n.layer == view_layer.name), None)
    if rl is None:
        rl = g.nodes.new("CompositorNodeRLayers")
        rl.name = rl.label = LAYERS_NODE_NAME
        rl.scene = scene
        rl.layer = view_layer.name
        rl.location = (-300, -400)
    directory = os.path.dirname(r.filepath).rstrip("\\/")
    directory = (directory + os.sep) if directory not in ("", "/") else "//"

    fo = _file_output(g, NODE_NAME, "Material ID file (odv)", (rl.location.x + 300, rl.location.y - 50))
    fo.directory = directory
    fo.format.color_mode = 'RGB'      # the AOV's alpha counts surfaces, it is not coverage
    _standard_view(fo, scene)

    pm = photo_match(g)
    catchers = pm is not None and any(
        # Lights report is_shadow_catcher = True in Blender 5.3; only rendered geometry counts.
        o.type in GEOMETRY and not o.hide_render and getattr(o, "is_shadow_catcher", False)
        for o in scene.objects)
    s = settings(scene)
    roles = pass_roles(view_layer, s)
    removed = _set_items(fo, [ITEM_NAME] + (["shadow"] if catchers else []) + roles[NODE_NAME])
    g.links.new(rl.outputs[AOV_NAME], fo.inputs[ITEM_NAME])
    if _setup_passes(g, scene, view_layer, rl, fo, roles, directory, s.denoise):
        removed = True
    passes = _passes_note(view_layer, s, roles)

    if pm is None:
        old = g.nodes.get(LAYERS_NODE)
        if old is not None:
            g.nodes.remove(old)
            removed = True
        if removed:
            _forget_queue_items()
        return ('INFO', "Post-production output set up: 16-bit PNG beauty, material ID file "
                        "and layered PSD" + passes)

    ao, rl_fg, photo = pm
    lo = _file_output(g, LAYERS_NODE, "Render and photo files (odv)", (ao.location.x, ao.location.y - 300))
    lo.directory = directory
    lo.format.color_mode = 'RGBA'
    lo.format.color_management = 'FOLLOW_SCENE'
    lo.save_as_render = True
    if _set_items(lo, ["render", "photo"]):
        removed = True
    g.links.new(ao.inputs["Foreground"].links[0].from_socket, lo.inputs["render"])
    g.links.new(photo, lo.inputs["photo"])
    if removed:
        _forget_queue_items()

    view_note = ""
    if scene.view_settings.view_transform != 'Standard' or scene.view_settings.look not in ('None', ''):
        view_note = (f". The view transform is {scene.view_settings.view_transform}: the shadow and photo "
                     "layers match Blender's result only with Standard and no look")
    if catchers:
        vl_fg = scene.view_layers.get(rl_fg.layer) or view_layer
        vl_fg.cycles.use_pass_shadow_catcher = True
        _shadow_multiply(g, ao, rl_fg, photo)
        g.links.new(rl_fg.outputs["Shadow Catcher"], fo.inputs["shadow"])
        return ('WARNING' if view_note else 'INFO',
                "Post-production output set up for a photo match: render, shadow (Multiply) "
                "and photo as separate PSD layers. The Shadow Catcher pass is on and the photo "
                "is multiplied by it in the compositor" + view_note + passes)
    m = g.nodes.get(MULTIPLY_NODE)
    if m is not None:
        g.links.new(photo, ao.inputs["Background"])
        g.nodes.remove(m)
    return ('WARNING' if view_note else 'INFO',
            "Post-production output set up for a photo match: render and photo as separate "
            "PSD layers (no shadow catcher objects)" + view_note + passes)


def status_lines(scene, view_layer):
    """(ok, text) lines for the panel."""
    r = scene.render
    im = r.image_settings
    fmt_ok = im.file_format == 'PNG' and im.color_depth == '16' and im.color_mode == 'RGBA'
    path = beauty_candidates(scene)[0]
    problem = output_problem(path)
    node = id_node(scene)
    return [
        (fmt_ok, "Output: 16-bit PNG with alpha" if fmt_ok else
         f"Output: {im.file_format} {im.color_depth}-bit {im.color_mode}"),
        (problem is None, f"Saves to: {os.path.basename(path)}" if problem is None else f"Output path: {problem}"),
        (AOV_NAME in view_layer.aovs, "Material ID AOV" if AOV_NAME in view_layer.aovs
         else "No material ID AOV: Assign material IDs"),
        (node is not None and not node.mute, "ID File Output node" if node else "No ID File Output node"),
        (r.use_compositing, "Compositing on" if r.use_compositing else "Compositing off: no ID file"),
    ] + _photo_lines(scene) + _pass_lines(scene, view_layer)


def _pass_lines(scene, view_layer):
    """Whether the File Output nodes carry the ticked extra passes, no more and no less."""
    s = settings(scene)
    want = {r for rs in pass_roles(view_layer, s).values() for r in rs}
    have = set()
    g = scene.compositing_node_group
    for name in (NODE_NAME, AIDS_NODE, LIGHT_NODE):
        node = g.nodes.get(name) if g else None
        if node is not None and node.bl_idname == "CompositorNodeOutputFile":
            names = _node_roles(node)
            have |= {_role(i.name, names) for i in node.file_output_items}
    have -= {None, ITEM_NAME, "shadow"}
    if not want and not have:
        return []
    if want == have:
        return [(True, f"Extra passes: {len(want)}")]
    missing, extra = sorted(want - have), sorted(have - want)
    text = "Run Set up output: " + "; ".join(
        p for p in (missing and "not set up: " + ", ".join(missing),
                    extra and "no longer ticked: " + ", ".join(extra)) if p)
    return [(False, text)]


def _photo_image(socket, depth=0):
    """The Image node upstream of a compositor socket, following the first linked input."""
    node = socket.node
    if node.bl_idname == "CompositorNodeImage":
        return node.image
    if depth > 8:
        return None
    for inp in node.inputs:
        if inp.is_linked:
            return _photo_image(inp.links[0].from_socket, depth + 1)
    return None


def _photo_lines(scene):
    pm = photo_match(scene.compositing_node_group)
    if pm is None:
        return []
    lines = [(True, "Photo match: render, shadow, photo layers")]
    img = _photo_image(pm[2])
    if img is not None and img.source in {'FILE', 'SEQUENCE'} and not img.packed_file:
        found = os.path.exists(bpy.path.abspath(img.filepath))
        lines.append((found, f"Photo: {img.name}" if found else f"Photo not found: {img.name} (File › External Data › Find Missing Files)"))
    return lines


# ---------------------------------------------------------------------------
# operators and panel
# ---------------------------------------------------------------------------

class ODV_OT_post_setup(bpy.types.Operator):
    bl_idname = "odv.post_setup"
    bl_label = "Set up output"
    bl_description = ("Set the scene's output to a 16-bit PNG with alpha (view transform applied), "
                      "add a File Output node that writes the Material ID with exact colours, and "
                      "switch on the layered PSD")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        level, message = setup(context.scene, context.view_layer)
        self.report({level}, message)
        return {'FINISHED'}


class ODV_OT_post_preset(bpy.types.Operator):
    bl_idname = "odv.post_preset"
    bl_label = "Pass preset"
    bl_description = "Tick the extra passes of a preset and run Set up output"
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(
        items=[(k, v[0], v[1]) for k, v in PRESETS.items()], default='MINIMAL')

    @classmethod
    def description(cls, context, properties):
        return PRESETS[properties.preset][1] + ". Runs Set up output"

    def execute(self, context):
        s = settings(context.scene)
        on = PRESETS[self.preset][2]
        for k in PASSES:
            setattr(s, "pass_" + k, k in on)
        level, message = setup(context.scene, context.view_layer)
        self.report({level}, message)
        return {'FINISHED'}


class ODV_OT_post_save_render(bpy.types.Operator, ExportHelper):
    bl_idname = "odv.post_save_render"
    bl_label = "Save Layered PSD"
    bl_description = ("Save the last render as a layered PSD with the material ID, choosing where; "
                      "the beauty and the separate pass files are saved next to it")

    filename_ext = ".psd"
    filter_glob: bpy.props.StringProperty(default="*.psd", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        job = _last["job"]
        return job is not None and bpy.data.images.get("Render Result") is not None

    def invoke(self, context, event):
        # Start from this render's name: the output path, or where it was saved last.
        # Set every time: the browser would otherwise offer the previous render's name.
        job = _last["job"]
        path = bpy.path.abspath(job.get("beauty_file") or job["beauty"][0])
        if path.startswith("//"):   # relative output path, .blend not saved: name only
            path = os.path.basename(path)
        self.filepath = os.path.splitext(path)[0] + self.filename_ext
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        job = dict(_last["job"])
        job["written"] = False
        if self.filepath:
            # The beauty goes next to the PSD under the same name, with its own extension.
            ext = os.path.splitext(job["beauty"][0])[1] or ".png"
            stem = os.path.splitext(bpy.path.abspath(self.filepath))[0]
            job["beauty"] = [os.path.normpath(stem + ext)]
        if start(job, save=True):
            self.report({'INFO'}, f"Saved {os.path.basename(job['beauty_file'])}; writing the PSD")
            return {'FINISHED'}
        self.report({'WARNING'}, _last["status"] or "Not saved")
        return {'CANCELLED'}


class ODV_OT_post_report(bpy.types.Operator):
    bl_idname = "odv.post_report"
    bl_label = "Report"
    bl_options = {'INTERNAL'}

    level: bpy.props.StringProperty(default='INFO')
    message: bpy.props.StringProperty()

    def execute(self, context):
        self.report({self.level}, self.message)
        return {'FINISHED'}


class ODV_PT_post_output(bpy.types.Panel):
    bl_label = "Post-production output"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "odv"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        s = settings(scene)
        layout.operator(ODV_OT_post_setup.bl_idname, icon='OUTPUT')
        col = layout.column(align=True)
        col.prop(s, "enabled")
        sub = col.column(align=True)
        sub.active = s.enabled
        sub.prop(s, "keep_separate")
        sub.prop(s, "save_f12")
        box = layout.box().column(align=True)
        for ok, text in status_lines(scene, context.view_layer):
            box.label(text=text, icon='CHECKMARK' if ok else 'ERROR')
        if _last["status"]:
            layout.label(text=_last["status"], icon='INFO')


class ODV_PT_post_passes(bpy.types.Panel):
    bl_label = "Extra passes"
    bl_parent_id = "ODV_PT_post_output"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "odv"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = settings(context.scene)
        world = context.scene.world
        row = layout.row(align=True)
        for key, (label, _tip, _on) in PRESETS.items():
            row.operator(ODV_OT_post_preset.bl_idname, text=label).preset = key
        layout.label(text="Ticks take effect with Set up output")

        col = layout.column(align=True)
        col.label(text="Greyscale, stretched per image")
        col.prop(s, "pass_mist")
        if s.pass_mist and world:
            sub = col.row(align=True)
            sub.prop(world.mist_settings, "start")
            sub.prop(world.mist_settings, "depth")
        col.prop(s, "pass_ao")
        if s.pass_ao and world:
            col.prop(world.light_settings, "distance", text="AO distance")

        col = layout.column(align=True)
        col.label(text="Colour, scene view transform")
        for k in ("lightgroups", "reflection", "refraction", "emission", "environment", "albedo"):
            col.prop(s, "pass_" + k)
        col.prop(s, "denoise")

        col = layout.column(align=True)
        col.label(text="Exact values")
        col.prop(s, "pass_aovs")


def _image_menu(self, context):
    self.layout.separator()
    self.layout.operator(ODV_OT_post_save_render.bl_idname, text="Save Layered PSD...",
                         icon='RENDERLAYERS')


classes = (ODV_PG_post_output, ODV_OT_post_setup, ODV_OT_post_preset, ODV_OT_post_save_render,
           ODV_OT_post_report, ODV_PT_post_output, ODV_PT_post_passes)

_handlers = (("render_pre", _on_render_pre), ("render_write", _on_render_write),
             ("render_complete", _on_render_complete), ("render_cancel", _on_render_cancel))


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.odv_post = bpy.props.PointerProperty(type=ODV_PG_post_output)
    bpy.types.IMAGE_MT_image.append(_image_menu)
    for name, fn in _handlers:
        getattr(bpy.app.handlers, name).append(fn)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=POLL_S, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for name, fn in _handlers:
        lst = getattr(bpy.app.handlers, name)
        if fn in lst:
            lst.remove(fn)
    if _worker is not None and _worker.is_alive():
        _work.put(None)
    bpy.types.IMAGE_MT_image.remove(_image_menu)
    del bpy.types.Scene.odv_post
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
