# AGENTS.md

Shared instructions for coding agents (Claude, Codex, Antigravity and others) in this repository.
Keep this file the single source of shared instructions; tool-specific files such as `CLAUDE.md` reference it rather than duplicate it.

## What this repository is

odv's tools for moving our work between Archicad, Rhino and Blender.
Blender is the hub where we render our own work; the tools bring models from Archicad and Rhino into a Blender scene and keep that scene up to date.
`README.md` describes the layout, `STATUS.md` what works and the evidence for it.

The repository is public. It is built for our own projects and maintained as we need it.

## Start here

- Read `README.md`, `STATUS.md` and the README of the tool you work on.
- Inspect `git status` and the recent commits, and preserve existing changes.
- Read the GitHub issues (`gh issue list -R odv-hu/blender`) and the full thread of the issue you work on (`gh issue view <n> --comments -R odv-hu/blender`). See "Issues and commits" below.

## Environment

| | |
|---|---|
| Host | macOS, Blender 5.1. Archicad and Rhino are the source apps. |
| Extension | The Blender tools ship as one extension, `odv_tools` (`blender_manifest.toml`, #3). The owner installs the built zip from disk; the installed copy is not updated by git. |
| Git client | The owner uses Fork. |

## Where the work happens

The owner's local checkout is the working copy.
Make changes there, in the files the task names, and leave them for the owner to review in Fork.

- Do not work in a separate clone (a cloud session, a temporary checkout) and push from it: the owner then has to fetch and pull changes he has not seen.
- Do not commit, push, force-push, rewrite history, tag, create, switch or delete branches, or delete files without the owner's explicit permission. A request to change files authorises the change in the working tree, not a commit.
- When the owner asks for a commit, commit in his local checkout. Pushing is his, unless he asks for it.

## Issues and commits

Open work lives in the GitHub issues of `odv-hu/blender`.
The issue thread is where the context of a piece of work is kept, so that someone with only the thread can continue it.
No milestones yet; the owner assigns them.

- **Before starting:** work from an issue. Read it with its comments. If the task has none, find a matching one or open one (small housekeeping such as typos needs none).
- **New problems:** a bug, limitation or follow-up you find but do not fix becomes a new issue, not a line in `STATUS.md` or a handoff note. Say what happens, where (tool, file, Blender version), the evidence (console output, scene, commit), and what "done" means. Labels: one type (`bug`, `limitation`, `enhancement`, `documentation`, `question`) and, once they exist, one area per source app (`archicad`, `rhino`, `blender`).
- **Commits:** every commit that works on an issue names it in the message body: `Refs #n` for progress, `Fixes #n` when the commit resolves it completely (GitHub closes it when the owner pushes to `main`).
- **Context in the thread:** when you stop working on an issue, or learn something the next person needs, comment: what was done (commit hashes), the checks run and their results, decisions and who took them, and what is left. No raw logs.
- **Owner decisions:** a question only the owner can answer goes into the issue as a comment ending with the question, with the `question` label; do not decide it in the code.
- **Closing:** when an issue is resolved, update the tool's README and `STATUS.md` where the behaviour or the evidence changed.
- **Without GitHub access** (no `gh`, no network): put the issue text or comment in your final message under "For the issue tracker", with the issue number, for the owner to post.

## Rules

**Public repository**
- No client or project names, no full paths (they contain the owner's account name), no credentials: not in code, comments, docs or commit messages.
- Do not name other companies' products or tools as the model for an approach in code or docs unless the owner asks for it.

**Code**
- Each tool lives in its own folder under the app it starts from (`archicad/`, `rhino/`, `blender/`), with a README that says what it does, how to use it, and its limitations.
- A Blender tool is a module of the `odv_tools` extension: a package `<app>/<tool>/` (underscores: it is a Python package) with `register()` and `unregister()`, listed in the root `__init__.py`. Its panel goes on the `odv` sidebar tab; class names start with `ODV_`, operator ids with `odv.`. Use relative imports.
- One version for the whole extension, in `blender_manifest.toml`. Record user-visible changes in `CHANGELOG.md` under *Unreleased*; the version is set at release (`docs/RELEASING.md`).
- Tools that run inside Rhino or Archicad are not part of the extension.
- Do not change the owner's installed add-ons, Blender preferences or open scenes while editing code. Reading them (for example through a Blender MCP connection) is fine; running code that changes a scene needs his go-ahead; never save his `.blend` files.

**Working with the owner**
- Proceed without asking when the task is clear; ask only when a choice is genuinely his.
- Explain the cause of an unexpected result, not just the fix.
- Plain, precise English.
- Never read, print or commit credentials.

## Verification

- Run `python3 -m py_compile` on every changed Python file and `git diff --check` on the change.
- For the extension: `blender --command extension validate .` and `blender --command extension build --output-dir dist`, then check the zip's contents.
- A headless check in a background Blender (`blender --factory-startup -b --python <test>`) that loads the built package can exercise operators on synthetic data without touching the owner's Blender. Say what it covers and what it does not.
- Blender-side behaviour can only be checked in Blender. Do not claim it works from reading the code: say what was not run, and describe the manual check (Blender version, scene, steps, expected result) for the owner.
- A recorded check goes into `STATUS.md` with its date, Blender version and commit.

## Releases

Read and follow `docs/RELEASING.md` whenever asked to build, package or release a version. Committing, tagging and pushing are the owner's; the pushed tag publishes the release through `.github/workflows/release.yml`. Change that workflow only with the owner's go-ahead.

## Handoff

List the changed files, the checks performed and their results, the issues worked on, and what is left.
Distinguish edited, committed and pushed states explicitly.
Remaining work goes into the issue thread or a new issue, not only into the handoff.
Always recommend a short commit message in the form `[area] Description` (`[repo]`, `[docs]`, `[git]`, `[release]`, or the tool, e.g. `[fbx_model_update]`), with `Refs #n` or `Fixes #n` in the body for each issue it touches, ending with a `Co-Authored-By:` line naming the assistant.
Do not execute the commit without permission.
