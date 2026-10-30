# STATUS

**Documented state:** `main` at `5ee1dda` (2026-10-30).

**Review status.** The code was written with AI assistance: the first updater script with ChatGPT (2026-04), the Archicad FBX Updater add-on v2.0.0 in an AI-assisted session that was not recorded (2026-08-26).
Neither has been reviewed line by line.
Treat it as working tools for our own projects, not reviewed software.

Legend: **Tested** = a recorded check with named data · **In use** = used in our projects, no recorded check · **Implemented** = in the code, not exercised on record · **Proposed** = discussed, not built.

## Tools

### Archicad FBX Updater (`archicad/fbx-model-update/`, add-on v2.0.0)

| Feature | Status | Evidence |
|---|---|---|
| Panel in the 3D Viewport sidebar, *AC* tab: FBX, Target, Temp, the two options and both buttons | **In use** | the owner's Blender 5.1.2 on macOS, installed 2026-08-26 |
| Update model from FBX: join the import, split by material, replace geometry inside existing objects, add new ones, empty missing ones | **In use** | the owner's projects; no recorded check of matched / new / missing handling |
| Assign pass indices; auto pass index for new objects | **In use** | as above |
| Import through either FBX importer (`wm.fbx_import` or `import_scene.fbx`) | Implemented | which one runs on Blender 5.1 is not recorded |
| Repository copy equals the installed copy | **Tested** | 2026-10-30: the files differ only in one reworded code comment |

### Rhino → Blender

Nothing yet.

## Known bugs and limitations

Open bugs and limitations are GitHub issues (https://github.com/odv-hu/blender/issues); this list is an index.

| Issue | Summary |
|---|---|
| #1 | Custom UV maps are lost on update (Archicad FBX Updater) |
| #2 | Archicad export settings for the add-on to be confirmed (question) |

## Most recently changed

- **2026-10-30 (Balázs + Claude):** a local file path removed from the whole history (force-push); the repository reorganised into per-app tool folders with a README describing its purpose; MIT licence; the add-on replaced the Text Editor script; agent instructions (`AGENTS.md`, `CLAUDE.md`) and this file added.

## Decisions waiting for the owner

- Archicad export settings for the add-on (#2).
- The repository is public, and the commits from before the history rewrite can still be opened on GitHub by their hash. Leave them, ask GitHub Support to purge them, or recreate the repository?
- The installed add-on still has the comment that was reworded in the repository copy. Reinstall from the repository?
- Area labels for issues (`archicad`, `rhino`, `blender`): create them?
