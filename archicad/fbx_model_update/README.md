# Archicad FBX Updater

Updates the Archicad model in a Blender scene from a new FBX export with one click.
Materials, pass indices, modifiers and custom properties set up in Blender are kept.

Part of the odv tools extension; see the [main README](../../README.md#install) to install it. Requires Blender 5.0 or newer; used with Blender 5.1.

The panel is in the 3D Viewport sidebar (N), on the *odv* tab.

**Coming from the stand-alone add-on** (`ac_fbx_updater.py`, *AC* tab): uninstall it before installing odv tools, because both define the same scene settings.
The settings saved in `.blend` files (FBX path, collections, options) keep working.

## Export from Archicad

1. File / Save As / FBX File (*.fbx)
2. Create FBX meshes by: Surface (one mesh per surface)
3. Surface settings to export: Export colors and transparency only.
4. Texture handling: Embed textures in FBX setting is OFF (leave it unchecked)

The Archicad surfaces arrive as materials.
Their settings are not needed: materials are set up in Blender.

## Use

| Field | |
| --- | --- |
| **FBX** | The exported file. |
| **Target** | The collection that holds the model in the scene, `ARCHICAD MODEL` by default. Created on the first update if it is missing. |
| **Temp** | A working collection for the import, `__TEMP_FBX__` by default. It is emptied after each update; don't render it. |
| **Clear missing objects** | Empty the geometry of objects that are no longer in the FBX. The objects themselves are kept. When off, they are left as they are. |
| **Auto pass index for new** | Give each new object the lowest pass index not yet used in the target collection. |
| **Merge by distance** | Weld vertices closer than the distance (0.1 mm by default) and remove faces without area. Off by default. |
| **Smooth by angle** | Shade smooth, with edges sharp where faces meet at more than the angle (30° by default). Off by default. |

*Target* and *Temp* are in the *Collections* sub-panel, closed by default.
*Update model from FBX* stays greyed out until an FBX file is selected.
Every field and button explains itself in its tooltip.

**Update model from FBX** imports the file, joins everything and splits it again into one object per material, named after the material, which is the Archicad surface.
Then it compares these with the objects in the target collection by name:

- **in the scene and in the FBX:** the geometry is replaced inside the existing object, so its materials, pass index, modifiers and custom properties stay;
- **new in the FBX:** the object is added to the target collection;
- **no longer in the FBX:** the object is emptied, if *Clear missing objects* is on.

The FBX arrives with every triangle on its own vertices.
The two *Clean-up* options work on each surface object after the split, before the matching, so they don't change which objects are matched:

- **Merge by distance** makes each surface one connected mesh. Modifiers that need connected geometry, such as Bevel, then work: on the separate triangles a Bevel modifier has no effect. UVs and the normals from the FBX are kept, so the shading does not change.
- **Smooth by angle** replaces the normals from the FBX with smooth shading and sharp edges, stored in the mesh rather than as a modifier. It only has an effect on welded geometry, so use it together with *Merge by distance*. On curved surfaces, check that the result looks better than the FBX normals.

Materials that arrive as duplicates (`Wood.001`) are pointed at the existing material (`Wood`), and unused duplicates are removed.
The result is shown in the status bar, and the matched, new and missing names are printed to the system console.
The update can be undone with Ctrl+Z.

**Assign pass indices** numbers every object in the target collection from 1 upwards, in name order, and gives the object's materials the same index.
This overwrites existing pass indices.
Pass indices are what the *Object Index* and *Material Index* passes use for masks in compositing.

## Limitations

- Custom UV maps are lost on update, because the geometry is replaced. Use procedural texture mapping.
- Object transforms are applied: the geometry sits in world coordinates and every object's transform is reset.
- *Merge by distance* also welds separate elements of the same surface where they touch. Where two elements share a face (a block standing on a block of the same surface), the hidden contact faces stay inside the mesh and the edges around them become non-manifold, which can trouble Bevel and smooth shading at that joint.
