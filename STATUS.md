# STATUS

**Documented state:** odv tools 0.0.1 (2026-10-30), the first release: the Blender tools packaged as one extension (#3).

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
| Release workflow (`.github/workflows/release.yml`): version checks, notes from `CHANGELOG.md`, build with Blender 5.1.2 on Linux, zip check, GitHub release | **Tested** (manual start) | run 41062487292, started by hand for `v0.0.1` on 2026-10-30: every step passed and it published the pre-release *odv tools 0.0.1* with `odv_tools-0.0.1.zip` (7,975 bytes, the same size as the local build). The push of the tag `v0.0.1` itself started no run; a tag push has not yet been seen to start the workflow |
| Extension repository on GitHub Pages (`https://blender.odv.hu/index.json`, #4): `server-generate` in the release workflow, Pages deploy | Implemented | not yet run on GitHub. Checked locally on 2026-10-30: `server-generate --html` with Blender 5.1.2 on `odv_tools-0.0.1.zip` writes `index.json` (one package, `archive_url` `./odv_tools-0.0.1.zip`, size and SHA-256) and `index.html`; actionlint 1.7.7 passes on the workflow. DNS: `blender.odv.hu` CNAME `odv-hu.github.io.` seen through Google and Cloudflare DNS; `odv.hu` verified for the organisation |
| Install from disk and use in the interactive Blender | **Tested** | owner, Blender 5.1.2 on macOS, 2026-10-30: `odv_tools-0.0.1.zip` installed from disk after uninstalling the stand-alone add-on, enabled as `bl_ext.user_default.odv_tools`, panel on the *odv* tab, update run on a real project |

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

- **2026-10-30 (#4, Balázs + Claude):** the release workflow also publishes the extension repository `https://blender.odv.hu/index.json` on GitHub Pages; `blender.odv.hu` set up at dima.hu and `odv.hu` verified on GitHub.
- **2026-10-30 (Balázs + Claude):** release workflow added: a pushed `vX.Y.Z` tag builds the zip with Blender and publishes the GitHub release.
- **2026-10-30 (Balázs + Claude):** odv tools 0.0.1 released, after the owner installed it and ran it on a real project.
- **2026-10-30 (#3, Balázs + Claude):** the Blender tools are packaged as one extension, `odv_tools` 0.0.1: `blender_manifest.toml`, root `__init__.py`, the updater as the module `archicad/fbx_model_update/` with its panel on the *odv* tab; `CHANGELOG.md` and `docs/RELEASING.md` added.
- **2026-10-30 (Balázs + Claude):** a local file path removed from the whole history (force-push); the repository reorganised into per-app tool folders with a README describing its purpose; MIT licence; the add-on replaced the Text Editor script; agent instructions (`AGENTS.md`, `CLAUDE.md`) and this file added.

## Decisions waiting for the owner

- Archicad export settings for the add-on (#2).
- The repository is public, and the commits from before the history rewrite can still be opened on GitHub by their hash. Leave them, ask GitHub Support to purge them, or recreate the repository?
- GitHub settings for the extension repository (#4): Pages source *GitHub Actions*, a `v*` tag rule on the `github-pages` environment, then the custom domain `blender.odv.hu` with HTTPS (`docs/RELEASING.md`).
- Area labels for issues (`archicad`, `rhino`, `blender`): create them?
