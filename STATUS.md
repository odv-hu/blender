# STATUS

**Documented state:** odv tools 0.0.1, not yet released: the Blender tools packaged as one extension (#3), 2026-10-30.

**Review status.** The code was written with AI assistance: the first updater script with ChatGPT (2026-04), the Archicad FBX Updater add-on v2.0.0 in an AI-assisted session that was not recorded (2026-08-26).
Neither has been reviewed line by line.
Treat it as working tools for our own projects, not reviewed software.

Legend: **Tested** = a recorded check with named data · **In use** = used in our projects, no recorded check · **Implemented** = in the code, not exercised on record · **Proposed** = discussed, not built.

## Tools

### Extension (`blender_manifest.toml`, `__init__.py`)

| Feature | Status | Evidence |
|---|---|---|
| Validate and build `odv_tools-0.0.1.zip` | **Tested** | Blender 5.1.2, macOS, 2026-10-30: `extension validate` passes; `extension build` gives a 7.7 kB zip with the manifest, `LICENSE`, the packages and the READMEs, without the agent docs, `STATUS.md` or `CHANGELOG.md` |
| Register and unregister | **Tested** | headless, below: panel on the *odv* tab, both operators present; nothing left after `unregister()` |
| Installing the zip from disk in the interactive Blender | not yet | |

### Archicad FBX Updater (`archicad/fbx_model_update/`)

| Feature | Status | Evidence |
|---|---|---|
| Panel: FBX, Target, Temp, the two options and both buttons | **In use** | as the stand-alone add-on v2.0.0 (*AC* tab) in the owner's Blender 5.1.2 on macOS, installed 2026-08-26 |
| Update and reindex from the extension package | **Tested** | headless, background Blender 5.1.2 with factory settings on macOS, 2026-10-30, package built from the working tree of #3. Synthetic FBX exports of three cube "elements" (materials Wall + Plaster, Wall, Glass), then the same with Steel instead of Glass. Run 1: Wall, Plaster, Glass added. Run 2: Wall and Plaster matched, Steel added with the next free pass index (3), Glass emptied (0 polygons). Wall kept a custom property, a bevel modifier, pass index 42 and a replaced material; the temp collection was empty and no `.001` materials were left. *Assign pass indices* gave 1–4 in name order. Not covered: a real Archicad FBX, the interactive UI |
| Update model from FBX: join the import, split by material, replace geometry inside existing objects, add new ones, empty missing ones | **In use** | the owner's projects; no recorded check of matched / new / missing handling |
| Assign pass indices; auto pass index for new objects | **In use** | as above |
| Import through either FBX importer (`wm.fbx_import` or `import_scene.fbx`) | Implemented | which one runs on Blender 5.1 is not recorded |

### Rhino → Blender

Nothing yet.

## Known bugs and limitations

Open bugs and limitations are GitHub issues (https://github.com/odv-hu/blender/issues); this list is an index.

| Issue | Summary |
|---|---|
| #1 | Custom UV maps are lost on update (Archicad FBX Updater) |
| #2 | Archicad export settings for the add-on to be confirmed (question) |
| #4 | Self-hosted extension repository for updates in Blender |

## Most recently changed

- **2026-10-30 (#3, Balázs + Claude):** the Blender tools are packaged as one extension, `odv_tools` 0.0.1: `blender_manifest.toml`, root `__init__.py`, the updater as the module `archicad/fbx_model_update/` with its panel on the *odv* tab; `CHANGELOG.md` and `docs/RELEASING.md` added.
- **2026-10-30 (Balázs + Claude):** a local file path removed from the whole history (force-push); the repository reorganised into per-app tool folders with a README describing its purpose; MIT licence; the add-on replaced the Text Editor script; agent instructions (`AGENTS.md`, `CLAUDE.md`) and this file added.

## Decisions waiting for the owner

- Archicad export settings for the add-on (#2).
- The repository is public, and the commits from before the history rewrite can still be opened on GitHub by their hash. Leave them, ask GitHub Support to purge them, or recreate the repository?
- Install odv tools 0.0.1 and uninstall the stand-alone Archicad FBX Updater add-on (both define the same scene settings).
- Hosting for the extension repository (#4).
- Area labels for issues (`archicad`, `rhino`, `blender`): create them?
