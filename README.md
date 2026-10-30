# blender

```Built for our own projects, maintained as we need it. Issues are welcome, but don't expect us to implement them: we work on this at our own pace, as our projects demand.```

Tools that make it easier to move our work between Archicad, Rhino and Blender.
We model in Archicad and Rhino and render in Blender, so Blender is the hub.
The tools here bring models from the other two into a Blender scene and keep that scene up to date as the models change, so materials, UVs and lighting don't have to be redone after every change.

## Tools

| Tool | From | What it does |
| --- | --- | --- |
| [fbx-model-update](archicad/fbx-model-update/) | Archicad | Updates the Archicad model in a Blender scene from a new FBX export and keeps the materials set up in Blender. |

## Layout

```
archicad/   Archicad → Blender
rhino/      Rhino → Blender
blender/    work inside Blender itself (UV mapping, scene clean-up, …)
```

Each tool gets its own folder under the app it starts from, with a README that says what it does and how to run it.
A tool can be a single script run from Blender's Scripting workspace or an installable add-on.

## Licence

[MIT](LICENSE)
