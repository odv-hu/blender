# Material ID

Gives every material a fixed flat colour and renders it to its own pass, the AOV `odv_matid`, for masks in post-production.
A material keeps its colour across cameras, scenes and re-renders, and neighbouring materials get colours that a magic-wand selection can tell apart.
The beauty render does not change.

Part of the odv tools extension; see the [main README](../../README.md#install) to install it. Requires Blender 5.0 or newer; checked with Blender 5.3.

The panel is in the 3D Viewport sidebar (N), on the *odv* tab.

## Use

| | |
| --- | --- |
| **Scenes** | *Active* or *All*: the scenes whose view layers get the `odv_matid` AOV. Materials are shared between scenes, so every material gets its colour either way. |
| **Assign material IDs** | Gives every material without an ID colour one, adds the ID nodes to every material and enables the AOV. Colours a material already has are kept. Run it again after adding materials, or after editing a colour by hand. |
| **Remove material IDs** | Removes the ID nodes from every material and the AOV from every view layer of every scene. The colours stay stored on the materials, so assigning again gives the same colours. *Forget colours* (in the operator panel after running it) deletes them too. |
| **Active material** | The active object's active material, its ID colour and **Re-roll**, which gives it a new colour as different as possible from all others. Use it when two neighbouring materials are hard to tell apart in the mask. Each press gives another colour. |

The result is shown in the status bar. The system console lists the materials whose ID follows their transparency, linked materials that were skipped, and the five closest pairs of colours.

To see the pass in Blender: in the 3D Viewport in *Rendered* shading, choose `odv_matid` in the *Render Pass* menu of the shading popover; in the compositor, the *Render Layers* node has an `odv_matid` output.
Writing the pass to a file is not part of this tool yet (#20).

## How the colours are chosen

The colour comes from the material name, so the same name gives the same colour in any file and on any machine.
Colours are bright (value 0.55 to 1) and saturated, because black is what the background and objects without a material give.
A new colour has to be at least ΔE 15 (CIE76) away from the colours already given; if the name's colour is closer, the next candidate for the same name is tried.
Materials are taken in name order, so the same set of names always gives the same colours.
On a real project with 65 materials, 40 kept the colour of their name and the closest pair is ΔE 15; straight from the names, there were 10 pairs closer than ΔE 5.

The colour is stored on the material as the custom property `odv_matid` (Material Properties › Custom Properties) and is not chosen again: renaming a material keeps its colour.
It is the colour as it appears in a file written with the *Standard* view transform on an sRGB display, on the 8-bit grid (n/255), so it is exact in 8- and 16-bit files.
It can be edited there or in the panel; press *Assign material IDs* afterwards to apply it to the nodes.

A copied material carries its original's colour. On the next *Assign*, the original keeps it and the copy gets a colour of its own.

## What it adds to a material

A frame *odv material ID* next to the Material Output, with an RGB node holding the colour, a mask for transparency, and an *AOV Output* node writing to `odv_matid`.
The nodes are tagged with the custom property `odv_matid`, so the tool finds, rebuilds and removes only its own nodes.
They are not connected to the surface shader, so the beauty render does not change (checked pixel by pixel, below).

**Transparency.** Cycles writes the AOV of every surface a camera ray passes through, until it reaches a surface whose alpha is at least the view layer's *Alpha Threshold* (0.5 by default), and adds them up.
A cut-out leaf would then write its colour over the whole card, added to the colour behind it.
So the ID is masked: a material writes its colour where its alpha is at least the threshold, and nothing where the ray passes on. This is the same rule the *Material Index* pass follows.
The tool follows the alpha from the *Surface* of the active Material Output to

- a *Principled BSDF*: its *Alpha* (a texture or a value),
- a *Mix Shader* with a *Transparent BSDF* on one side: its factor.

Any other set-up counts as opaque. The threshold is read from the active view layer when *Assign* or *Re-roll* runs.

## Limitations

- **Edges are anti-aliased.** The AOV goes through the same pixel filter as the beauty (*Filter › Pixel Filter*, 1.5 px by default), so colours blend at boundaries. In a 200 × 100 test render, 87 % of the pixels were exactly one ID colour. Use some tolerance or grow the selection by a pixel.
- **Surfaces less opaque than the threshold** do not appear in the ID, and the colour behind them is dimmed by their transparency (×0.84 behind an alpha of 0.2 in Cycles), so it is no longer exact. To include faint glass, lower the view layer's *Alpha Threshold* and assign again; it also changes the other data passes.
- **EEVEE** handles partial transparency by dithering, so half-transparent surfaces blend with what is behind them, and its AOV values differ from the exact colour by up to about 1/65535 in a 16-bit file. Cut-outs (alpha 0 or 1) are exact.
- **Objects without a material** are black in the ID.
- **Alpha inside node groups**, or set up other than in the two ways above, is not followed: such a material counts as opaque.
- **Linked materials** (from another .blend) and Grease Pencil materials are skipped.
- **New materials** (for example from an Archicad FBX update) have no ID until *Assign* runs again. Materials kept by the Archicad FBX Updater keep their ID nodes and colours.
