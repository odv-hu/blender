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

from . import psd
from ..material_id import AOV_NAME

NODE_NAME = "odv_matid"       # File Output, Standard view, 16-bit RGB: matid, shadow
LAYERS_NODE = "odv_layers"    # File Output, scene view transform, 16-bit RGBA: render, photo
MULTIPLY_NODE = "odv_shadow_multiply"
ITEM_NAME = "matid"
ROLES = ("matid", "shadow", "render", "photo")   # file <beauty>_<role>.png
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
                    "When off, use Image › Save Layered PSD in the Image Editor")


def settings(scene):
    return getattr(scene, "odv_post", None)


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


def _role(item_name):
    """matid, shadow, render or photo; a render queue may prefix the item names."""
    for role in ROLES:
        if item_name == role or item_name.endswith("_" + role):
            return role
    return None


def item_files(scene):
    """{role: file} that our File Output nodes write in this render: directory +
    file name + item name. Photographer renames the items for each camera."""
    out = {}
    g = scene.compositing_node_group
    if g is None or not scene.render.use_compositing:
        return out
    for node_name in (NODE_NAME, LAYERS_NODE):
        node = g.nodes.get(node_name)
        if node is None or node.bl_idname != "CompositorNodeOutputFile" or node.mute:
            continue
        directory = bpy.path.abspath(node.directory)
        for i, item in enumerate(node.file_output_items):
            role = _role(item.name)
            if role is None or not node.inputs[i].is_linked:
                continue
            name = node.file_name + item.name
            if node.use_file_extension and node.format.file_format == 'PNG':
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
        expected = [(l.name, l.visible, l.blend.decode("ascii")) for l in layers]
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
    # drive than the beauty, so move with shutil (copies when it has to).
    try:
        if job["keep"]:
            for role, path in used.items():
                target = f"{stem}_{role}.png"
                if os.path.normcase(path) != os.path.normcase(target):
                    shutil.move(path, target)
                    job["items"][role] = target
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
        role = _role(item.name)
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


def _standard_view(node, scene):
    """Write values as they are, without the scene's look: exact ID colours, a shadow
    factor that multiplies correctly on display values."""
    node.format.color_management = 'OVERRIDE'
    node.format.display_settings.display_device = scene.display_settings.display_device
    vs = node.format.view_settings
    vs.view_transform = 'Standard'
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
    removed = _set_items(fo, [ITEM_NAME, "shadow"] if catchers else [ITEM_NAME])
    g.links.new(rl.outputs[AOV_NAME], fo.inputs[ITEM_NAME])

    if pm is None:
        old = g.nodes.get(LAYERS_NODE)
        if old is not None:
            g.nodes.remove(old)
            removed = True
        if removed:
            _forget_queue_items()
        return ('INFO', "Post-production output set up: 16-bit PNG beauty, material ID file "
                        "and layered PSD")

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
                "is multiplied by it in the compositor" + view_note)
    m = g.nodes.get(MULTIPLY_NODE)
    if m is not None:
        g.links.new(photo, ao.inputs["Background"])
        g.nodes.remove(m)
    return ('WARNING' if view_note else 'INFO',
            "Post-production output set up for a photo match: render and photo as separate "
            "PSD layers (no shadow catcher objects)" + view_note)


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
    ] + _photo_lines(scene)


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


class ODV_OT_post_save_render(bpy.types.Operator):
    bl_idname = "odv.post_save_render"
    bl_label = "Save Layered PSD"
    bl_description = ("Save the last F12 render to the scene's output path and write the layered PSD "
                      "with the material ID next to it")

    @classmethod
    def poll(cls, context):
        job = _last["job"]
        return job is not None and bpy.data.images.get("Render Result") is not None

    def execute(self, context):
        job = dict(_last["job"])
        job["written"] = False
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


def _image_menu(self, context):
    self.layout.separator()
    self.layout.operator(ODV_OT_post_save_render.bl_idname, icon='RENDERLAYERS')


classes = (ODV_PG_post_output, ODV_OT_post_setup, ODV_OT_post_save_render,
           ODV_OT_post_report, ODV_PT_post_output)

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
