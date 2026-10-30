# Releasing

The repository releases one product: the `odv_tools` Blender extension (#3).
Its version is `version` in `blender_manifest.toml`, follows semantic versioning, and is tagged `vX.Y.Z` on `main`.
Tools that run inside Rhino or Archicad are not part of the extension; they will get their own release form when they exist.

## Steps

1. Everything for the release is on `main`, and `CHANGELOG.md` lists it under *Unreleased*.
2. Set `version` in `blender_manifest.toml` to `X.Y.Z`. Rename the *Unreleased* section of `CHANGELOG.md` to `X.Y.Z (YYYY-MM-DD)` and start a new, empty *Unreleased* section. Update the documented state in `STATUS.md`.
3. Validate and build from the repository root:

   ```sh
   blender --command extension validate .
   blender --command extension build --output-dir dist
   ```

   On macOS, `blender` is `Blender.app/Contents/MacOS/Blender`. Create `dist/` first if it does not exist; it is git-ignored.
   Check the contents with `unzip -l dist/odv_tools-X.Y.Z.zip`: no `AGENTS.md`, `CLAUDE.md`, `STATUS.md`, `CHANGELOG.md` or `docs/`.
4. Install the zip in Blender (*Edit › Preferences › Add-ons*, ˅ menu at the top right, *Install from Disk…*) and run each tool on a real project file. Record the check in `STATUS.md` with the date, Blender version and commit.
5. The owner commits (`[release] vX.Y.Z`), tags `vX.Y.Z` and pushes.
6. Create a GitHub Release named `odv tools X.Y.Z`, with the `CHANGELOG.md` section as its text and the zip attached.

Installing from a self-hosted extension repository, so that Blender offers updates, is not set up yet (#4).
