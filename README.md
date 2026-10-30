# blender

```Built for our own projects, maintained as we need it. Issues are welcome, but don't expect us to implement them: we work on this at our own pace, as our projects demand.```

Tools that make it easier to move our work between Archicad, Rhino and Blender.
We model in Archicad and Rhino and render in Blender, so Blender is the hub.
The tools here bring models from the other two into a Blender scene and keep that scene up to date as the models change, so materials, UVs and lighting don't have to be redone after every change.

## Install

The Blender tools ship together as one extension, **odv tools**, for Blender 5.0 or newer.

1. Download `odv_tools-X.Y.Z.zip` from the [Releases](https://github.com/odv-hu/blender/releases) page, or build it yourself (`docs/RELEASING.md`).
2. In Blender, open *Edit › Preferences › Add-ons*, click the ˅ menu at the top right and choose *Install from Disk…*.
3. Select the zip. The tools appear in the 3D Viewport sidebar (N), on the *odv* tab.

## Tools

| Tool | From | What it does |
| --- | --- | --- |
| [Archicad FBX Updater](archicad/fbx_model_update/) | Archicad | Updates the Archicad model in a Blender scene from a new FBX export and keeps the materials, pass indices and modifiers set up in Blender. |

## Layout

```
archicad/   Archicad → Blender
rhino/      Rhino → Blender
blender/    work inside Blender itself (UV mapping, scene clean-up, …)
```

Each Blender tool is a module of the extension, in its own folder under the app it starts from, with a README that says what it does and how to use it.
Tools that have to run inside Rhino or Archicad live under that app's folder too, but are not part of the Blender extension.
Changes are listed in `CHANGELOG.md`; releases are described in `docs/RELEASING.md`.

## Licence

[MIT](LICENSE)
