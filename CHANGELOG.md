# Changelog

User-visible changes to the odv tools extension.
Versions follow semantic versioning; tags are `vX.Y.Z` on `main` (see `docs/RELEASING.md`).

## Unreleased

## 0.0.3 (2026-11-11)

### Added

- Archicad FBX Updater (#10): optional *Clean-up* during an update, both off by default. *Merge by distance* welds the separate triangles of each surface and removes faces without area, so modifiers such as Bevel work; *Smooth by angle* shades smooth with sharp edges above an angle, replacing the normals from the FBX.

## 0.0.2 (2026-10-30)

### Changed

- Archicad FBX Updater (#5): tooltips for the update button and every field; *Update model from FBX* is greyed out until an FBX file is selected; the two options sit in an *Options* box, and *Target* and *Temp* in a *Collections* sub-panel, closed by default.

## 0.0.1 (2026-10-30)

### Added

- The Blender tools are packaged as one extension, `odv_tools` (#3). Every tool draws its panel on the *odv* tab of the 3D Viewport sidebar.
- Archicad FBX Updater, from the stand-alone add-on v2.0.0: updates the Archicad model from a new FBX export, grouped by surface, keeping materials, pass indices, modifiers and custom properties; assigns pass indices.

### Changed

- Archicad FBX Updater: the panel moved from the *AC* tab to *odv*, and the operators are now `odv.ac_update_from_fbx` and `odv.ac_reindex`. The scene settings (FBX path, collections, options) keep their names, so `.blend` files used with the old add-on keep them.
