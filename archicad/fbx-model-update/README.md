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

## Install

This is a plain script, not an add-on: there is nothing to install in Preferences.
It is loaded into each `.blend` file that should be updated.

1. Get the script: download [`update-ac-model-fbx.py`](update-ac-model-fbx.py) (*Download raw file* on GitHub), or clone the repo.
2. In Blender, switch to the *Scripting* workspace.
3. In the Text Editor, choose *Text › Open…* and select `update-ac-model-fbx.py`.

The opened script stays linked to the file on disk.
When the file changes, for example after a `git pull`, the Text Editor offers to reload it.
To keep a fixed copy inside the `.blend` instead, choose *Make Text Internal* from that prompt.

## Run in Blender

1. Set `FBX_PATH` to the exported file. Keep the `r` and the quotes: `FBX_PATH = r"C:\path\to\model.fbx"`.
2. Run the script: the ▶ (*Run Script*) button in the Text Editor header, or Alt+P.

The model lives in a collection named `ARCHICAD MODEL`, created on the first run if it is missing.
The script prints the matched, new and missing objects to the system console (*Window › Toggle System Console* on Windows; on macOS and Linux, the terminal Blender was started from).
Save the `.blend` before the first run, so you can go back if the result is not what you expected.

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
