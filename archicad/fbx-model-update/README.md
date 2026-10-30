# fbx-model-update

Archicad FBX Updater: a Blender add-on that updates the Archicad model in a scene from a new FBX export with one click.
Materials, pass indices, modifiers and custom properties set up in Blender are kept.

Requires Blender 5.0 or newer; used with Blender 5.1.

## Install

1. Download [`ac_fbx_updater.py`](ac_fbx_updater.py) (*Download raw file* on GitHub), or clone the repo.
2. In Blender, open *Edit › Preferences › Add-ons*, click the ˅ menu at the top right and choose *Install from Disk…*.
3. Select `ac_fbx_updater.py`, then tick *Archicad FBX Updater* in the list to enable it.

The panel appears in the 3D Viewport sidebar (N), on the *AC* tab.

Blender copies the file into its own add-ons folder, so pulling a new version from the repo does not update the installed one.
To update, install the new file the same way; it replaces the old one.

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

**Update model from FBX** imports the file, joins everything and splits it again into one object per material, named after the material, which is the Archicad surface.
Then it compares these with the objects in the target collection by name:

- **in the scene and in the FBX:** the geometry is replaced inside the existing object, so its materials, pass index, modifiers and custom properties stay;
- **new in the FBX:** the object is added to the target collection;
- **no longer in the FBX:** the object is emptied, if *Clear missing objects* is on.

Materials that arrive as duplicates (`Wood.001`) are pointed at the existing material (`Wood`), and unused duplicates are removed.
The result is shown in the status bar, and the matched, new and missing names are printed to the system console.
The update can be undone with Ctrl+Z.

**Assign pass indices** numbers every object in the target collection from 1 upwards, in name order, and gives the object's materials the same index.
This overwrites existing pass indices.
Pass indices are what the *Object Index* and *Material Index* passes use for masks in compositing.

## Limitations

- Custom UV maps are lost on update, because the geometry is replaced. Use procedural texture mapping.
- Object transforms are applied: the geometry sits in world coordinates and every object's transform is reset.
