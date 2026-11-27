# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Personal command-line tools shared with the e-reader team (Vivlio / TEA-ebook). Each tool is a single self-contained script in its own folder, with its own `README.md`. The tools do not share code. The repo has no build, test suite or CI.

## Install and run

`setup.sh` symlinks each script into a folder in `PATH` (default `~/.local/bin`). Each link has the name of the tool folder, not the script name. Run `./setup.sh -u` to remove the links.

When you add a tool, add its script path to the `SCRIPTS` array in `setup.sh` and a line to the tool list in the root `README.md`.

## Code quality

Without CI, pre-commit is the only quality gate (`.pre-commit-config.yaml`): shellcheck and shfmt for shell scripts (shfmt style in `.editorconfig`), `ruff check` and `ruff format` for Python (rules in `ruff.toml`), and generic file checks (whitespace, shebang, executable bit). Run `pre-commit run --all-files` after a change and fix every finding before you commit. Do not disable a check to make it pass.

Most tools call live Jira or Azure DevOps APIs and can change tickets: ask before you run one.

## Conventions

- Some logic is copied between tools instead of shared (for example the Jira ticket-id parsing). When you change it in one tool, look for the same code in the others.
- Optional external tools (`fzf`, `wtp`, `gh`, ...) are detected with `command -v`, and the script has a fallback.
- Each script has a usage and dependency header comment that matches its README. Update both together.
- READMEs use short, simple English sentences (Simplified Technical English style), in the present tense and active voice.
- Commit messages follow Conventional Commits (`feat`, `fix`, `build`, `chore`, `ci`, `docs`, `perf`, `refactor`, `revert`, `style`, `test`), with the tool folder as scope: `feat(create-branch-from-jira): support tickets of any Jira project`. A commit-msg hook enforces it. Older commits use a `[tool]` prefix; do not copy that style.
