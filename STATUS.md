# STATUS

**Documented state:** odv tools 0.0.4 (2026-11-11): new tool *Material ID*, one fixed flat colour per material in the AOV `odv_matid` (#19). 0.0.3 (2026-11-11): optional clean-up on update in the Archicad FBX Updater, *Merge by distance* and *Smooth by angle* (#10). 0.0.2 (2026-10-30): panel improvements of the Archicad FBX Updater (#5), released to test updates from the extension repository (#4). 0.0.1 was the first release: the Blender tools packaged as one extension (#3).

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
| Release workflow (`.github/workflows/release.yml`): version checks, notes from `CHANGELOG.md`, build with Blender 5.1.2 on Linux, zip check, GitHub release | **Tested** | started by a tag push: run 42983635045 for `v0.0.4` (2026-11-11, commit `2e7547d`), every step passed with `actions/checkout@v7`, `actions/upload-pages-artifact@v5` and `actions/deploy-pages@v5`, and no Node 20 warning (#18); run 41067394449 for `v0.0.2` (2026-10-30), every step passed. Started by hand: run 41062487292 for `v0.0.1`; the `v0.0.1` tag push started no run because Actions was not yet switched on |
| Extension repository on GitHub Pages (`https://blender.odv.hu/index.json`, #4): `server-generate` in the release workflow, Pages deploy, updates in Blender | **Tested** | 2026-10-30: 0.0.1 published by run 41065700587 and installed from the repository in the owner's Blender 5.1.2 (macOS); 0.0.2 published by the tag-push run 41067394449 and offered and installed as an update in the same Blender. 2026-11-11: 0.0.4 published by the tag-push run 42983635045 (`index.json` generated with 0.0.4, Pages deploy reported success); the update in Blender not yet recorded |
| Install from disk and use in the interactive Blender | **Tested** | owner, Blender 5.1.2 on macOS, 2026-10-30: `odv_tools-0.0.1.zip` installed from disk after uninstalling the stand-alone add-on, enabled as `bl_ext.user_default.odv_tools`, panel on the *odv* tab, update run on a real project |

### Archicad FBX Updater (`archicad/fbx_model_update/`)

| Feature | Status | Evidence |
|---|---|---|
| Panel: FBX, Target, Temp, the two options and both buttons | **In use** | as the stand-alone add-on v2.0.0 (*AC* tab) in the owner's Blender 5.1.2 on macOS, installed 2026-08-26 |
| Update and reindex from the extension package | **Tested** | headless, background Blender 5.1.2 with factory settings on macOS, 2026-10-30, package built from the working tree of #3. Synthetic FBX exports of three cube "elements" (materials Wall + Plaster, Wall, Glass), then the same with Steel instead of Glass. Run 1: Wall, Plaster, Glass added. Run 2: Wall and Plaster matched, Steel added with the next free pass index (3), Glass emptied (0 polygons). Wall kept a custom property, a bevel modifier, pass index 42 and a replaced material; the temp collection was empty and no `.001` materials were left. *Assign pass indices* gave 1–4 in name order. Not covered: a real Archicad FBX, the interactive UI |
| Panel of 0.0.2 (#5): tooltips, update button disabled without an FBX, *Collections* sub-panel | **Tested** headless; panel look not yet seen | background Blender 5.1.2 with factory settings on macOS, 2026-10-30, `odv_tools-0.0.2.zip` built from the working tree: the operator's `poll()` is false with an empty FBX path and true with one; the *Collections* sub-panel is registered under the main panel, closed by default; the operator and all five scene settings have descriptions. The update test above repeated with the same result (Wall kept its custom property, modifier and pass index 42; Glass emptied; Steel added) |
| Clean-up on update (#10): *Merge by distance*, *Smooth by angle*, both off by default | **Tested** headless; not yet run on a real Archicad FBX or seen in the UI | `bpy` 5.1.2 (Blender as a Python module) on Linux, factory settings, 2026-11-11, working tree on `506baf8`, also from the built zip. Synthetic FBX exports with every triangle on its own vertices: cubes (Wall + Plaster top, Wall, Glass → Bronze), two Concrete cubes sharing a face, a 32-sided Steel cylinder. Update run with the clean-up off, merge only, merge + smooth and smooth only: the same matched / new / missing names every time; Wall kept its custom property, pass index 42 and Bevel modifier. Merge: Wall 66 → 16 vertices, Steel 372 → 64, Plaster 6 → 4, the FBX normals kept; the Bevel modifier went from no effect (22 faces) to 58 faces. Smooth: FBX normals removed, Steel sharp only on the two cap rims (64 edges). Side effect: the two Concrete cubes keep their contact faces inside and get 4 non-manifold edges. Smooth alone changes nothing visible on flat surfaces |
| Update model from FBX: join the import, split by material, replace geometry inside existing objects, add new ones, empty missing ones | **In use** | the owner's projects; no recorded check of matched / new / missing handling |
| Assign pass indices; auto pass index for new objects | **In use** | as above |
| Import through either FBX importer (`wm.fbx_import` or `import_scene.fbx`) | Implemented | which one runs on Blender 5.1 is not recorded |

### Material ID (`blender/material_id/`, #19)

| Feature | Status | Evidence |
|---|---|---|
| *Assign material IDs*: colours from names kept ΔE 15 apart, stored on the materials; ID nodes in every material; AOV on the active or all scenes; repeat runs; hand-set and copied colours; *Re-roll*; *Remove material IDs* (with and without *Forget colours*); unregister | **Tested** headless; panel not yet seen | `tests/test_material_id.py`, `bpy` 5.3.0 (Blender as a Python module) on Linux, factory settings, 2026-11-11, working tree on `336116d`, from the working tree and from the built zip: 52 of 52 checks pass. Two scenes sharing one collection (three view layers), 14 materials. Repeat runs change no colour and add no node; *Active* puts the AOV on the active scene only, *All* once on every view layer; a hand-set colour is kept and applied; a copied material gets its own colour; two re-rolls give two new colours (ΔE ≥ 58 from all others); removal leaves no node and no AOV and keeps the colours, assigning again gives the same colours. Repeated with `odv_tools-0.0.4.zip` built from the working tree, on `bpy` 5.3.0 and on `bpy` 5.0.1 (the minimum in the manifest): 52 of 52 both |
| Beauty unchanged | **Tested** headless | same run: Cycles on the CPU, 200 × 100 px, 32 samples, fixed seed and threads; the beauty is pixel-identical (max difference 0.0) without the nodes, with them, and after removing them |
| AOV values, transparency | **Tested** headless (Cycles); EEVEE probed | same run: opaque materials write their exact colour; behind a cut-out (Principled *Alpha* from a texture, and *Mix Shader* with *Transparent BSDF*) the colour behind is exact; a constant alpha of 0.5 (= *Alpha Threshold*) writes the material's exact colour; behind an alpha of 0.2 the colour behind is dimmed ×0.84; no material is black; 87.4 % of the pixels are exactly one ID colour (pixel filter 1.5 px). A probe without the mask showed the cause: Cycles adds the AOV of every surface up to the first with alpha ≥ threshold, so a fully transparent card wrote its colour on top of the one behind. Probe, same set-up: through a *File Output* node with the *Standard* view, 16-bit PNG, Cycles gave the exact colour (0, 128, 255); EEVEE dithers partial alpha and was off by about 1/65535 |
| ID nodes and colours survive an update with the Archicad FBX Updater | **Tested** headless | same run: synthetic FBX export of three surfaces (Wall, Floor, Brick), *Update model from FBX* into the collection: the three materials keep their ID nodes and colours, no `.001` materials left |
| Colours on a real project | **Tested** read-only | owner's Blender 5.3.0 on Windows, 2026-11-11, a real project file (5 scenes, one shared collection, 65 materials, all pass indices 0), file not changed: colours computed only, closest pair ΔE 15.2, 40 of 65 straight from the name (from the names alone: one identical pair and 10 closer than ΔE 5); the same 65 colours as `bpy` 5.3.0 on Linux (equal digest); four materials with a constant alpha (0, 0.31, 0.77, 0.78) recognised, the 0.31 one below the threshold. Not run on it: *Assign*, a render of the ID |
| Panel in the interactive Blender, ID render of a real scene | Implemented | not run |

### Rhino → Blender

Nothing yet.

## Known bugs and limitations

Open bugs and limitations are GitHub issues (https://github.com/odv-hu/blender/issues); this list is an index.

| Issue | Summary |
|---|---|
| #1 | Custom UV maps are lost on update (Archicad FBX Updater) |
| #2 | Archicad export settings for the add-on to be confirmed (question) |

## Most recently changed

- **2026-11-11 (#18, Balázs + Claude):** release workflow moved to actions that run on Node 24: `actions/checkout@v7`, `actions/upload-pages-artifact@v5`, `actions/deploy-pages@v5`; the `v0.0.4` run 42983635045 passed every step without the Node 20 warning, published the GitHub release and the extension repository listing 0.0.4.
- **2026-11-11 (#19, Balázs + Claude):** new tool *Material ID*: one fixed flat colour per material in the AOV `odv_matid`, masked by transparency; headless test `tests/test_material_id.py`; read-only check of the colours on a real project. Released as 0.0.4.
- **2026-11-11 (#10, Balázs + Claude):** Archicad FBX Updater: optional *Merge by distance* and *Smooth by angle* during an update, off by default; tested headless, released as 0.0.3.
- **2026-10-30 (#4, Balázs + Claude):** 0.0.2 released by a tag push and offered as an update in Blender; #4 closed.
- **2026-10-30 (#5, Balázs + Claude):** Archicad FBX Updater panel: tooltips, update button disabled without an FBX, *Options* box and closed *Collections* sub-panel; released as 0.0.2.
- **2026-10-30 (#4, Balázs + Claude):** GitHub Pages switched on (source *GitHub Actions*, tag rule `v*` on `github-pages`, custom domain `blender.odv.hu`); 0.0.1 published to the extension repository and installed from it in Blender.
- **2026-10-30 (#4, Balázs + Claude):** the release workflow also publishes the extension repository `https://blender.odv.hu/index.json` on GitHub Pages; `blender.odv.hu` set up at dima.hu and `odv.hu` verified on GitHub.
- **2026-10-30 (Balázs + Claude):** release workflow added: a pushed `vX.Y.Z` tag builds the zip with Blender and publishes the GitHub release.
- **2026-10-30 (Balázs + Claude):** odv tools 0.0.1 released, after the owner installed it and ran it on a real project.
- **2026-10-30 (#3, Balázs + Claude):** the Blender tools are packaged as one extension, `odv_tools` 0.0.1: `blender_manifest.toml`, root `__init__.py`, the updater as the module `archicad/fbx_model_update/` with its panel on the *odv* tab; `CHANGELOG.md` and `docs/RELEASING.md` added.
- **2026-10-30 (Balázs + Claude):** a local file path removed from the whole history (force-push); the repository reorganised into per-app tool folders with a README describing its purpose; MIT licence; the add-on replaced the Text Editor script; agent instructions (`AGENTS.md`, `CLAUDE.md`) and this file added.

## Decisions waiting for the owner

- Archicad export settings for the add-on (#2).
- The repository is public, and the commits from before the history rewrite can still be opened on GitHub by their hash. Leave them, ask GitHub Support to purge them, or recreate the repository?
- Area labels for issues (`archicad`, `rhino`, `blender`): create them?
