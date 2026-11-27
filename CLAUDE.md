# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Personal command-line tools shared with the e-reader team (Vivlio / TEA-ebook). Each tool is a single self-contained script in its own folder, with its own `README.md`. The tools do not share code and the repo has no build, linter, or test suite.

## Install and run

`setup.sh` symlinks each script into a folder in `PATH` (default `~/.local/bin`). Each link has the name of the tool folder, not the script name. Run `./setup.sh -u` to remove the links.

When you add a tool, add its script path to the `SCRIPTS` array in `setup.sh` and a line to the tool list in the root `README.md`.

To check a script without running it: `bash -n <script>.sh` or `python3 -m py_compile <script>.py`. Most tools call live Jira or Azure DevOps APIs.

## Conventions

- Some logic is copied between tools instead of shared (for example the Jira ticket-id parsing). When you change it in one tool, look for the same code in the others.
- Optional external tools (`fzf`, `wtp`, `gh`, ...) are detected with `command -v`, and the script has a fallback.
- Each script has a usage and dependency header comment that matches its README. Update both together.
- READMEs use short, simple English sentences (Simplified Technical English style), in the present tense and active voice.
- Commit messages start with the tool name in brackets, for example `[create-branch-from-jira] Support tickets of any Jira project`.
