# Post-production output

Per camera, three files for post-production that open in the image editor looking as they do in Blender, with no colour-space set-up on the editing machine:

| File | What |
| --- | --- |
| `<name>.png` | The beauty: 16-bit PNG with alpha, the scene's view transform applied. |
| `<name>_matid.png` | The [Material ID](../material_id/) pass: 16-bit PNG, written with the *Standard* view so the ID colours are exact. |
| `<name>.psd` | Both as one layered 16-bit PSD: `matid` on top (hidden), `beauty` below (visible, alpha as layer transparency). In a photo-match scene the render, its shadows and the photo are separate layers instead; see [Photo match](#photo-match). |
| `<name>_<pass>.png` | Optional [extra passes](#extra-passes) as post-production aids (mist, AO, light groups, …), each also a hidden layer in the PSD. |

Part of the odv tools extension; see the [main README](../../README.md#install) to install it. Requires Blender 5.0 or newer; checked with Blender 5.3 on Windows.

The panel is in the 3D Viewport sidebar (N), on the *odv* tab.

## Cameras and batch rendering: Photographer

This workflow is built around [Photographer](https://sites.google.com/view/photographer-5-documentation/), a separate, third-party camera manager add-on (checked with 5.8.4).
Cameras, per-camera overrides (resolution, film transparency, world, collection snapshots) and batch rendering are Photographer's job.
This tool only sets up the scene's output and the ID File Output node, and writes the PSD after each render.

Settings in Photographer's render queue:
- frame mode *Still*;
- `$camera` in the output path when rendering several cameras with incremental names; otherwise Photographer stops and asks first;
- *Overwrite File Output nodes* is not needed: the ID file is moved next to the beauty either way. *Add File Output node name* has no effect in Blender 5.

The queue renders the renderable cameras of the active scene only, through that scene's compositor.

With one photo per scene (a scene per photo-match camera), use *Render Active* in each scene: the *renderable* flag is stored on the camera and shared by every scene that uses it, so *Render All Enabled* in one scene would lay every camera over that scene's photo.

Photographer 5.8.4 keeps references to the File Output items it renames in a list that lives as long as Blender runs, and renames them all again on its next run. If an item has been removed in the meantime, Blender crashes. *Set up output* therefore keeps its items when run again, and when it does remove one, it empties that list. Deleting a File Output node by hand and then running the queue in the same Blender session can still crash; restart Blender first.

## Use

| | |
| --- | --- |
| **Set up output** | Sets the scene's output to a 16-bit PNG with alpha (view transform applied), switches compositing on, adds the File Output node `odv_matid` to the scene's compositor (fed by the `odv_matid` AOV of the active view layer) and switches the layered PSD on. In a photo-match scene it also adds the File Output node `odv_layers` and the shadow multiply (see [Photo match](#photo-match)). Run *Assign material IDs* first; without the AOV, only the output format is set. Running it again does not add nodes twice. |
| **Layered PSD** | Write `<name>.psd` after each render. |
| **Keep separate files** | Keep the beauty and ID PNGs next to the PSD. When off, they are deleted once the PSD has been written and read back; if anything fails, they are kept. |
| **Save F12 renders** | After an F12 render, save the beauty to the output path and write the PSD. When off, an F12 render is not saved; *Image › Save Layered PSD* in the Image Editor saves the last one. |
| **Extra passes** (sub-panel) | The [extra passes](#extra-passes), ticked one by one or with a preset. |

The box below the settings shows what is missing: output format, output path, the AOV, the ID node, compositing.
The result of each PSD is shown in the status bar and the system console.

## Photo match

When the scene's compositor lays the render over a photo with an *Alpha Over* node just before the output, *Set up output* keeps them apart in the PSD:

| Layer (top to bottom) | Blend | Visible | Content | Separate file |
| --- | --- | --- | --- | --- |
| `matid` | Normal | no | Material ID | `<name>_matid.png` |
| `composite` | Normal | no | Blender's own result, for reference | `<name>.png` |
| `render` | Normal | yes | The render, alpha as transparency, without the shadows | `<name>_render.png` |
| `shadow` | Multiply | yes | Cycles' *Shadow Catcher* pass | `<name>_shadow.png` |
| `photo` | Normal | yes | The photo as it enters the *Alpha Over* | `<name>_photo.png` |

With shadow catcher objects in the scene, *Set up* switches the view layer's *Shadow Catcher* pass on and adds a *Mix* node (Multiply, `odv_shadow_multiply`) that multiplies the photo by it before the *Alpha Over*.
That is needed: with the pass on, Cycles leaves the shadows out of the *Combined* pass, so without the multiply the shadows would disappear from Blender's own result.
It is also the more precise way: on a real project the result changed by 0.24 of 255 on average.
Run *Set up* again after removing the shadow catchers and the multiply is taken out again.

Why the shadows are a layer of their own: an image editor blends layers on display values, Blender's compositor in linear light.
For Normal blending that makes semi-transparent pixels darker in the editor; with the shadows in the render layer, they looked much stronger than in Blender (up to 70 of 255).
Multiply on display values is almost the same as multiplying in linear light, so the shadow layer matches Blender.

Measured on a real project (Blender 5.3, Standard view, synthetic black-and-white checker as the photo): over the whole image the stack differs from Blender's result by 0.23 of 255 on average (99 % of pixels within 1.8); in the shadows by 0.67 on average.

What does not match:
- **Object edges.** The anti-aliased edge pixels of the render (1–2 px) still blend on display values: on the checker, 16 of 255 on average, up to 70. The hidden `composite` layer is Blender's exact result.
- **Light on the shadow catcher.** Light that other objects bounce or reflect onto a shadow catcher is in the *Combined* pass as colour without alpha, which a layer with straight alpha cannot carry. It is missing from the stack (on the real project, 0.13 % of the transparent pixels, up to 36 of 255) but is in `composite`. (#30)
- **View transforms other than Standard.** The shadow and photo layers match only with the *Standard* view and no look; *Set up* warns otherwise. Photo matches usually use Standard so that the photo stays as it is.

## Extra passes

Post-production aids for painting over and adjusting: masks, haze, light. The beauty is always delivered as rendered; these passes are not meant to rebuild it.
Each ticked pass is written as `<name>_<pass>.png` and becomes a hidden layer in the PSD, with the blend mode it is usually used with.

| Pass | Layer | Blend | From Cycles | Written as |
| --- | --- | --- | --- | --- |
| Mist | `mist` | Screen | Mist pass; *Start* and *Depth* (the world's mist settings) in the panel | greyscale, stretched to black–white per image |
| AO | `ao` | Multiply | Ambient Occlusion pass; *AO distance* in the panel | greyscale, stretched to black–white per image |
| Light groups | `light_<group>` | Linear Dodge (Add) | one per light group of the view layer (*View Layer › Light Groups*) | colour, scene view transform, denoised |
| Reflection | `reflection` | Linear Dodge (Add) | (Glossy Direct + Indirect) × Glossy Color | colour, scene view transform, denoised |
| Refraction | `refraction` | Linear Dodge (Add) | (Transmission Direct + Indirect) × Transmission Color | colour, scene view transform, denoised |
| Emission | `emission` | Linear Dodge (Add) | Emission pass | colour, scene view transform |
| Environment | `environment` | Linear Dodge (Add) | Environment pass | colour, scene view transform |
| Albedo | `albedo` | Normal | Diffuse Color pass | colour, scene view transform |
| Custom AOVs | `aov_<name>` | Normal | every AOV of the view layer except `odv_matid` | exact values, Standard view |

Layer order, top to bottom: `matid`, custom AOVs, `mist`, `ao`, the Add layers, `albedo`, then the beauty (or the photo-match layers). All extra layers are hidden.

**Presets.** *Minimal*: no extra passes. *Photo match*: AO. *Full*: everything except environment and albedo. A preset ticks its passes and runs *Set up output*; ticking by hand takes effect with the next *Set up output*. The status box says when the ticks and the set-up differ.

**One layer per pass.** The checklist adds to what *Set up* already puts into the PSD: `render`, `shadow` and `photo` in a photo match, and `matid`. The shadow catcher is not in the checklist because a photo match delivers it as `shadow` already.

**Set up output** turns on the Cycles passes the ticked aids need and adds two File Output nodes: `odv_aids` (mist and AO, *Raw* view, so the values are linear before stretching) and `odv_light` (light groups and light passes, the scene's view transform). Custom AOVs go to the ID node (`odv_matid`, Standard view). Light groups, reflection and refraction get a compositor *Denoise* node each (*Denoise light passes*, on by default), because Cycles denoises only the Combined pass. Unticking a pass and running *Set up* again removes its nodes and items; the Cycles passes stay on.

**Stretched per image.** Mist and AO are stretched from the darkest to the lightest value of each render, so the same grey means different distances in different cameras. They are meant to be adjusted in post.

**Add layers are brighter than Blender.** An image editor adds the layers' display values, Blender adds light in linear light. Measured (headless, Standard view, two light groups covering every light): in linear light the light groups add up to the beauty exactly (max difference 0.0 of 255), on display values the Add stack is brighter by 37 of 255 on average, up to 52. Switch them on one at a time, or lower their opacity.

## When the PSD is written

- When Blender writes the render: Photographer's render queue, a command-line render, *Render › Render Image* with an output written by a script.
- After F12, with *Save F12 renders* on and an output path with a file name. F12 saves to the output path as typed, so the next F12 render overwrites the same files.
- From the Image Editor: *Image › Save Layered PSD* saves the last F12 render.

The beauty file name is the output path plus `.png` (Blender 5.3 writes a still without a frame number). The ID file is `<beauty name>_matid.png` and the PSD `<beauty name>.psd`, in the beauty's folder.
If a render has no ID file (Material ID not assigned, the node muted, compositing off), the PSD has the beauty layer only and a warning is shown.

The PSD is written on a separate thread after the render, so neither the interface nor a running queue waits for it. At 3120 × 2080 that takes a few seconds.

## The PSD

- 16-bit RGB, the canvas size of the render, with the beauty's colour profile (sRGB from Blender) embedded. Blender 5.0 and 5.1 write the PNG without a profile, so the PSD has none either; image editors then assume sRGB.
- Layers: `matid` (Normal, 100 %, hidden) above `beauty` (Normal, 100 %, visible; the render's alpha as layer transparency, straight, not premultiplied); the [extra passes](#extra-passes) between them, hidden.
- Layer channels ZIP-compressed with prediction; the merged composite uncompressed, so that the PSD thumbnail handler on Windows can draw a preview.
- Written by a small writer in this module (`psd.py`, numpy and the Python standard library only); checked in the image editor on Windows (#21).

## Limitations

- Stills only; animations are not handled.
- Extra passes not yet available: an edge mask (#27), object IDs (#28), line art (#29).
- Light groups and light passes stacked as Add layers do not add up to the beauty in the image editor (see [Extra passes](#extra-passes)).
- Only the photo-match set-up described above is recognised: an *Alpha Over* fed by the *Render Layers* image, directly before the output. Other compositor set-ups give the scene's output as one `beauty` layer.
- Uses `Scene.compositing_node_group`, which Blender 5.3 marks as deprecated, to be removed in Blender 6.0. Photographer uses it too.
- If the output format is changed after *Set up* to one that stores premultiplied alpha (Blender's TIFF does), the colour is converted back to straight alpha, which loses precision where the beauty is nearly transparent.
- Checked on Windows only; macOS (Finder previews, the image editor) is not checked yet.

## Manual check

Blender 5.3, a scene with material IDs assigned and two cameras:
1. *Set up output*: the box shows five ticks.
2. F12: `<name>.png`, `<name>_matid.png` and `<name>.psd` appear in the output folder; the status bar reports the PSD.
3. Open the PSD in the image editor: 16-bit RGB, layers `matid` (hidden) and `beauty`, transparency where the render is transparent, the same look as Blender's Image Editor.
4. Photographer's render queue, renderable cameras, `$camera` in the output path: the files for each camera.
5. Photo-match scene: *Set up output* again; F12; the PSD has `render`, `shadow` (Multiply) and `photo` visible, and switching `composite` on shows nearly the same image.
6. *Keep separate files* off, F12: only the PSD is left.
7. A scene with two light groups, a glass and an emitting object: *Extra passes › Full*; the status box shows *Extra passes* ticked. F12: the PSD has the beauty visible and hidden layers `light_<group>`, `reflection`, `refraction`, `emission` (Linear Dodge), `ao` (Multiply), `mist` (Screen) under `matid`; mist and AO span black to white. *Minimal*: the extra nodes are gone from the compositor.
