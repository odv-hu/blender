# fbx-model-update

Updates the Archicad model in a Blender scene from a new FBX export with a single script run.
Materials set up in Blender are kept.

## Export from Archicad

1. File / Save As / FBX File (*.fbx)
2. Create FBX meshes by: Surface (one mesh per surface)
3. Surface settings to export: Export colors and transparency only.
4. Texture handling: Embed textures in FBX setting is OFF (leave it unchecked)

This gives a stable structure based on the Surface attributes: one mesh per surface.
Materials are set in Blender anyway, so the surface settings themselves are not needed.

## Run in Blender

1. Open `update-ac-model-fbx.py` in the Text Editor (Scripting workspace).
2. Set `FBX_PATH` to the exported file.
3. Run the script.

The model lives in a collection named `ARCHICAD MODEL`, created on the first run if it is missing.
The script prints the matched, new and missing objects to the system console.

## What it does

Objects are matched by name, which is the Archicad surface name:

- **in the scene and in the FBX:** the geometry is replaced, the Blender materials are kept;
- **new in the FBX:** the object is added, and any material that already exists in the scene under the same name is reused (`Wood.001` → `Wood`);
- **no longer in the FBX:** the object is kept, but its geometry is emptied.

The import goes through a temporary `__TEMP_FBX__` collection, which is emptied at the end; don't render it.
Unused duplicate materials (`.001`, `.002`, …) are removed.

## Limitations

- Custom UV maps are lost on update: copying them over doesn't work yet. Use procedural texture mapping.
- The file path is set in the script; a file browser is on the to-do list.
