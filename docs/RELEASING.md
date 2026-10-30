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
5. The owner commits (`[release] vX.Y.Z`), tags that commit `vX.Y.Z` (in Fork: right-click the commit, *New Tag…*) and pushes `main` with the tag.
6. The tag starts `.github/workflows/release.yml`, which publishes the release; nothing is uploaded by hand. It checks that the tag, `blender_manifest.toml`, the Documented state line of `STATUS.md` and a `## X.Y.Z (YYYY-MM-DD)` section of `CHANGELOG.md` agree; validates and builds the zip with a pinned Blender; checks the zip's contents; and publishes the GitHub release `odv tools X.Y.Z` with the `CHANGELOG.md` section and the zip. 0.x versions are marked as pre-releases.

If the workflow fails, fix the cause on `main` and run it by hand from the *Actions* tab (*Release › Run workflow*) with the existing tag. It never replaces an existing release.

The workflow builds with the Blender version pinned in its `BLENDER_VERSION` and `BLENDER_SHA256`. To move to a newer Blender, change both; the checksum of `blender-X.Y.Z-linux-x64.tar.xz` is in `blender-X.Y.Z.sha256` on download.blender.org.

Installing from a self-hosted extension repository, so that Blender offers updates, is not set up yet (#4).
