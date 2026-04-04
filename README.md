# Purpose of the script collection
There are many workflow tasks which are hindering design: updating models from Archicad, UV-mapping, etc.

## Updating Archicad models
This is the backbone script: the workflow should allow for a single-click update for the ARCHICAD MODEL collection in the scene.
Current implementation works based on FBX models. You need to use the following settings in Archicad:

1. File / Save As / FBX File (*.fbx)
2. Create FBX meshes by: Surface (one mesh per surface)
3. Surface settings to export: Export colors and transparency only.
4. Texture handling: Embed textures in FBX setting is OFF (leave it unchecked)

This way we will get a stable structure from Archicad based on the Surface attributes.
As materials will get updated in Blender anyway, we do not need any surface settings.
