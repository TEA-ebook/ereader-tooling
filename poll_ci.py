#!/usr/bin/env python3
"""Poll an Azure DevOps pipeline build until it completes.

Usage:
  poll.py [-C REPO_PATH] [-l|--logs] [BUILD_ID | BRANCH]

  -C REPO_PATH      path to the git repository to use for branch/commit
                     lookups (default: current directory). Use this when
                     running poll.py from outside the target repo.
  -l, --logs        once the build completes, open an interactive picker
                     (fzf if available, else a numbered menu) to browse any
                     task's log. Requires a real terminal (stdin+stdout);
                     ignored otherwise. Without this flag, the picker is
                     never opened automatically.
  No argument → uses the current git branch.
  A numeric argument is treated as a build ID directly.
  A non-numeric argument is treated as a branch name; the latest build for
  that branch is fetched (searches push builds, then PR builds).

  While a build is still running, type 'l' + Enter at the "Next poll in..."
  prompt to open the same interactive log picker at any time (independent
  of -l/--logs, which only controls auto-opening on completion).

  If the build fails or partially succeeds, the failing tasks' log tails
  are always printed automatically, regardless of -l/--logs.

  When the repo is on GitHub and the `gh` CLI is authenticated, the pull
  request for the branch is inspected too: a conflicting PR is reported up
  front (GitHub stops refreshing refs/pull/N/merge, so no fresh check can
  run), and a check whose commit no longer matches the PR head is flagged
  as stale. PR lookups are best-effort and skipped when gh is unavailable.

Required env vars:
  AZURE_ORG          organisation name  (e.g. "myorg" from dev.azure.com/myorg)
  AZURE_PROJECT      project name
  AZURE_PAT          Personal Access Token with "Build (read)" scope

Optional:
  AZURE_PIPELINE_ID  pipeline definition ID (narrows searches to one pipeline)
  POLL_INTERVAL      seconds between polls (default: 30)
  LOG_TAIL           max lines shown per task in non-interactive mode (default: 80)
  NEW_BUILD_TIMEOUT  seconds to wait for a build matching the local HEAD commit
                      to appear before falling back to "latest queued" (default: 60)
"""

import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time

import requests

sys.stdout.reconfigure(line_buffering=True)

# ── terminal colours ──────────────────────────────────────────────────────────
if sys.stdout.isatty():
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN = "\033[0;36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
else:
    RED = GREEN = YELLOW = CYAN = BOLD = DIM = RESET = ""


def die(msg):
    print(f"{RED}error:{RESET} {msg}", file=sys.stderr)
    sys.exit(1)


def info(msg):
    print(f"{CYAN}▸{RESET} {msg}")


def speak(text):
    if shutil.which("espeak-ng"):
        subprocess.run(
            ["espeak-ng", "-v", "en", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


# ── config ────────────────────────────────────────────────────────────────────
def env_required(name, hint):
    value = os.environ.get(name)
    if not value:
        die(f"Set {name} to {hint}")
    return value


AZURE_ORG = env_required("AZURE_ORG", "your Azure DevOps organisation name")
AZURE_PROJECT = env_required("AZURE_PROJECT", "your Azure DevOps project name")
AZURE_PAT = env_required(
    "AZURE_PAT", "a Personal Access Token with Build (read) scope"
)
AZURE_PIPELINE_ID = os.environ.get("AZURE_PIPELINE_ID", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
LOG_TAIL = int(os.environ.get("LOG_TAIL", "80"))
NEW_BUILD_TIMEOUT = int(os.environ.get("NEW_BUILD_TIMEOUT", "60"))

BASE_URL = f"https://dev.azure.com/{AZURE_ORG}/{AZURE_PROJECT}/_apis"
API_VER = "api-version=7.1"


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _az_check_status(code):
    if 200 <= code < 300:
        return
    if code == 401:
        die(
            "Azure API returned 401 – PAT is invalid or expired\n"
            "       Generate a new one at https://tea-ebook.visualstudio.com/_usersSettings/tokens (Scopes: Builds → Read)\n"
            "       then export AZURE_PAT=<token>"
        )
    elif code == 403:
        die("Azure API returned 403 – PAT lacks required permissions (needs Build: read)")
    else:
        die(f"Azure API returned {code} – check AZURE_ORG and AZURE_PROJECT")


def az_get(url):
    resp = requests.get(url, auth=("", AZURE_PAT), headers={"Accept": "application/json"}, timeout=30)
    _az_check_status(resp.status_code)
    return resp.json()


def az_get_text(url):
    resp = requests.get(url, auth=("", AZURE_PAT), timeout=30)
    _az_check_status(resp.status_code)
    return resp.text


# ── GitHub PR state ───────────────────────────────────────────────────────────
PR_FIELDS = "number,title,state,isDraft,mergeable,mergeStateStatus,headRefOid,baseRefName,url"


def gh_pr_info(repo_path, ref="", repo_slug=""):
    """Return `gh pr view` data for a branch or PR number, or None.

    PR data is a bonus, never a requirement: give up quietly when gh is
    missing or unauthenticated, when the repo is not on GitHub, or when the
    branch has no pull request.

    A first query only asks GitHub to *start* computing mergeability, which
    comes back as UNKNOWN, so retry once before believing it.
    """
    if not shutil.which("gh"):
        return None
    cmd = ["gh", "pr", "view"]
    if ref:
        cmd.append(str(ref))
    if repo_slug:
        cmd += ["-R", repo_slug]
    cmd += ["--json", PR_FIELDS]

    pr = None
    for attempt in range(2):
        if attempt:
            time.sleep(2)
        try:
            proc = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=20
            )
        except (OSError, subprocess.SubprocessError):
            return pr
        if proc.returncode != 0:
            return pr
        try:
            pr = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return pr
        if pr.get("mergeable") != "UNKNOWN":
            break
    return pr


def pr_is_conflicting(pr):
    return bool(pr) and (
        pr.get("mergeable") == "CONFLICTING" or pr.get("mergeStateStatus") == "DIRTY"
    )


def pr_state_line(pr):
    mergeable = pr.get("mergeable") or "UNKNOWN"
    if pr_is_conflicting(pr):
        state = f"{RED}✘  conflicting{RESET}"
    elif mergeable == "MERGEABLE":
        state = f"{GREEN}✔  mergeable{RESET}"
    elif mergeable == "UNKNOWN":
        state = f"{YELLOW}?  mergeability unknown{RESET}"
    else:
        state = f"{YELLOW}{mergeable.lower()}{RESET}"
    status = (pr.get("mergeStateStatus") or "").lower()
    extra = f"  {DIM}({status}){RESET}" if status not in ("", "dirty", "clean") else ""
    draft = f"  {DIM}[draft]{RESET}" if pr.get("isDraft") else ""
    return f"#{pr.get('number')} → {pr.get('baseRefName', '?')}  {state}{extra}{draft}"


def conflict_lines(pr):
    """Explain why a conflicting PR gets no fresh check."""
    number = pr.get("number")
    base = pr.get("baseRefName") or "the base branch"
    return [
        f"{RED}{BOLD}PR #{number} conflicts with {base}{RESET}",
        f"GitHub stops updating refs/pull/{number}/merge while the PR is conflicting,",
        "so the pipeline runs no new check on the current head until you rebase or",
        "merge and push. Any check shown below ran on an older merge commit.",
    ]


def conflict_warning_lines(pr, indent="  "):
    lines = conflict_lines(pr)
    return [f"{indent}{RED}⚠{RESET}  {lines[0]}"] + [
        f"{indent}    {line}" for line in lines[1:]
    ]


def print_conflict_warning(pr, indent="  "):
    print("\n".join(conflict_warning_lines(pr, indent)))


# ── resolve build ID ──────────────────────────────────────────────────────────
def git_repo(repo_path, *args):
    return subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
    )


def parse_args(argv):
    repo_path = "."
    show_logs = False
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-C", "--repo"):
            if i + 1 >= len(argv):
                die("-C/--repo requires a path")
            repo_path = argv[i + 1]
            i += 2
        elif arg.startswith("--repo="):
            repo_path = arg[len("--repo=") :]
            i += 1
        elif arg.startswith("-C") and arg != "-C":
            repo_path = arg[2:]
            i += 1
        elif arg in ("-l", "--logs"):
            show_logs = True
            i += 1
        else:
            rest = argv[i:]
            break
    return repo_path, show_logs, rest


def resolve_build_id(repo_path, arg):
    if not arg:
        result = git_repo(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        if result.returncode != 0 or not result.stdout.strip():
            die(
                f"No argument given and no git repository found at '{repo_path}' (use -C to point at one)"
            )
        arg = result.stdout.strip()
        info(f"No build ID supplied – using current branch: {BOLD}{arg}{RESET}")

    if re.fullmatch(r"[0-9]+", arg):
        return arg

    branch = arg
    def_filter = f"definitions={AZURE_PIPELINE_ID}&" if AZURE_PIPELINE_ID else ""

    def match_build(sha):
        builds_url = (
            f"{BASE_URL}/build/builds?{def_filter}branchName=refs/heads/{branch}"
            f"&queryOrder=queueTimeDescending&$top=5&{API_VER}"
        )
        for build in az_get(builds_url).get("value", []):
            if build.get("sourceVersion") == sha:
                return str(build["id"])

        pr_url = (
            f"{BASE_URL}/build/builds?{def_filter}reasonFilter=pullRequest"
            f"&queryOrder=queueTimeDescending&$top=50&{API_VER}"
        )
        for build in az_get(pr_url).get("value", []):
            trigger = build.get("triggerInfo", {})
            if (
                trigger.get("pr.sourceBranch", "").removeprefix("refs/heads/") == branch
                and trigger.get("pr.sourceSha") == sha
            ):
                return str(build["id"])
        return None

    sha_result = git_repo(repo_path, "rev-parse", branch)
    sha = sha_result.stdout.strip() if sha_result.returncode == 0 else ""
    build_id = ""

    pr = gh_pr_info(repo_path, branch)
    wait_for_sha = bool(sha)
    if pr_is_conflicting(pr):
        print()
        print_conflict_warning(pr, indent="")
        print()
        # No merge ref will be built for this head, so don't burn
        # NEW_BUILD_TIMEOUT waiting for a build that cannot appear.
        wait_for_sha = False
    elif pr and sha and pr.get("headRefOid") and pr["headRefOid"] != sha:
        info(
            f"{YELLOW}PR #{pr['number']} head is {pr['headRefOid'][:8]}, "
            f"local HEAD is {sha[:8]} – unpushed commits?{RESET}"
        )

    if wait_for_sha:
        def wait_line(extra=""):
            return f"Waiting for a build of commit {BOLD}{sha[:8]}{RESET} on branch {BOLD}{branch}{RESET} ...{extra}"

        live = sys.stdout.isatty()
        if live:
            print(f"{CYAN}▸{RESET} {wait_line()}", end="", flush=True)
        else:
            info(wait_line())

        MATCH_POLL_INTERVAL = 5
        DISPLAY_REFRESH_INTERVAL = 1

        match_elapsed = 0
        while match_elapsed < NEW_BUILD_TIMEOUT and not build_id:
            if match_elapsed % MATCH_POLL_INTERVAL == 0:
                build_id = match_build(sha) or ""
                if build_id:
                    break
            time.sleep(DISPLAY_REFRESH_INTERVAL)
            match_elapsed += DISPLAY_REFRESH_INTERVAL
            if live:
                print(f"\r{CYAN}▸{RESET} {wait_line(f'  ({match_elapsed}s)')}", end="", flush=True)

        if live:
            print()
        if not build_id:
            info(
                f"No build found for commit {sha[:8]} within {NEW_BUILD_TIMEOUT}s; "
                "falling back to latest queued build."
            )

    if not build_id:
        info(f"Fetching latest push build for branch {BOLD}{branch}{RESET} ...")
        builds_url = (
            f"{BASE_URL}/build/builds?{def_filter}branchName=refs/heads/{branch}"
            f"&queryOrder=queueTimeDescending&$top=1&{API_VER}"
        )
        response = az_get(builds_url)
        values = response.get("value", [])
        if values:
            build_id = str(values[0]["id"])

    if not build_id:
        info(f"No push build found; searching PR builds for branch {BOLD}{branch}{RESET} ...")
        pr_url = (
            f"{BASE_URL}/build/builds?{def_filter}reasonFilter=pullRequest"
            f"&queryOrder=queueTimeDescending&$top=50&{API_VER}"
        )
        pr_response = az_get(pr_url)
        for build in pr_response.get("value", []):
            source_branch = build.get("triggerInfo", {}).get("pr.sourceBranch", "")
            if source_branch.removeprefix("refs/heads/") == branch:
                build_id = str(build["id"])
                break

    if not build_id:
        die(f"No build found for branch '{branch}' (set AZURE_PIPELINE_ID to narrow the search)")

    return build_id


# ── status formatting ─────────────────────────────────────────────────────────
def status_icon(state, result="-"):
    if state == "completed":
        if result == "succeeded":
            return f"{GREEN}✔  succeeded{RESET}"
        elif result == "partiallySucceeded":
            return f"{YELLOW}⚠  partial{RESET}"
        elif result == "failed":
            return f"{RED}✘  failed{RESET}"
        elif result == "canceled":
            return f"{YELLOW}⊘  canceled{RESET}"
        else:
            return f"{YELLOW}?  {result}{RESET}"
    elif state == "inProgress":
        return f"{CYAN}...  running{RESET}"
    elif state == "notStarted":
        return f"{DIM}⏸  queued{RESET}"
    else:
        return state


def result_icon(result):
    if result == "succeeded":
        return f"{GREEN}✔{RESET}"
    elif result == "failed":
        return f"{RED}✘{RESET}"
    elif result == "partiallySucceeded":
        return f"{YELLOW}⚠{RESET}"
    elif result in ("skipped", "canceled"):
        return f"{DIM}⊘{RESET}"
    else:
        return f"{DIM}·{RESET}"


def duration_fmt(secs):
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m{secs % 60:02d}s"


# ── log fetching ──────────────────────────────────────────────────────────────
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+ ", re.MULTILINE)


def fetch_log(build_id, log_id):
    try:
        text = az_get_text(f"{BASE_URL}/build/builds/{build_id}/logs/{log_id}?{API_VER}")
    except SystemExit:
        raise
    except Exception:
        return ""
    return TIMESTAMP_RE.sub("", text)


def open_in_viewer(build_id, log_id):
    content = fetch_log(build_id, log_id)
    editor = os.environ.get("EDITOR", "")
    if editor:
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="azdo-log-", suffix=".log", delete=False
        ) as tmp:
            tmp.write(content)
            tmpfile = tmp.name
        try:
            subprocess.run([*editor.split(), tmpfile])
        finally:
            os.unlink(tmpfile)
    else:
        pager = subprocess.Popen(["more"], stdin=subprocess.PIPE)
        pager.communicate(content.encode())


def task_entries(timeline):
    records = timeline.get("records", [])
    names = {r["id"]: r.get("name", "") for r in records}
    entries = []
    for r in records:
        if r.get("type") == "Task" and r.get("log"):
            log_id = str(r["log"]["id"])
            result = r.get("result") or "unknown"
            label = f"{names.get(r.get('parentId'), '?')} / {r.get('name', '')}"
            entries.append((log_id, result, label))
    return entries


# ── interactive log browser ───────────────────────────────────────────────────
def _browse_fzf(build_id, entries):
    fzf_lines = [f"{log_id}\t{result_icon(result)}  {label}" for log_id, result, label in entries]
    fzf_input = "\n".join(fzf_lines) + "\n"

    while True:
        proc = subprocess.run(
            [
                "fzf",
                "--ansi",
                "--no-sort",
                "--delimiter=\t",
                "--with-nth=2",
                "--prompt=task log ❯ ",
                "--header=Enter=view log   Esc/q=quit",
                "--bind=q:abort",
                "--height=~50%",
            ],
            input=fzf_input,
            stdout=subprocess.PIPE,
            text=True,
        )
        if proc.returncode == 2:
            # fzf couldn't drive the terminal (e.g. no controlling tty);
            # its own error already printed to stderr. Fall back instead
            # of looking like a silent hang.
            info(f"{YELLOW}fzf failed; falling back to the numbered menu.{RESET}")
            _browse_numbered(build_id, entries)
            return
        if proc.returncode != 0 or not proc.stdout.strip():
            break
        log_id = proc.stdout.split("\t")[0]
        open_in_viewer(build_id, log_id)


def _browse_numbered(build_id, entries):
    labels = [f"{result_icon(result)}  {label}" for _, result, label in entries]
    log_ids = [log_id for log_id, _, _ in entries]

    while True:
        print(f"\n{BOLD}Task logs — enter a number to view, q to quit:{RESET}\n")
        for i, label in enumerate(labels):
            print(f"  {i + 1:3d}  {label}")
        print()

        try:
            choice = input("  Choice: ")
        except EOFError:
            break
        if choice.lower() == "q":
            break
        if choice.isdigit() and 1 <= int(choice) <= len(log_ids):
            print()
            open_in_viewer(build_id, log_ids[int(choice) - 1])
        else:
            print(f"{YELLOW}  Enter a number between 1 and {len(log_ids)}, or q.{RESET}")


def browse_logs(build_id, timeline):
    entries = task_entries(timeline)
    if not entries:
        info("No task logs available.")
        return

    if shutil.which("fzf"):
        _browse_fzf(build_id, entries)
    else:
        _browse_numbered(build_id, entries)


def dump_logs(build_id, timeline, failed_only):
    entries = task_entries(timeline)
    if not entries:
        return

    print(f"\n{BOLD}Task logs:{RESET}")
    for log_id, result, label in entries:
        if failed_only and result != "failed":
            continue
        colour = RED if result == "failed" else DIM
        print(f"\n{colour}── {label}{RESET}")
        content = fetch_log(build_id, log_id)
        lines = content.splitlines()
        print("\n".join(lines[-LOG_TAIL:]))


# ── poll loop ─────────────────────────────────────────────────────────────────
def main():
    repo_path, show_logs, rest = parse_args(sys.argv[1:])
    arg = rest[0] if rest else ""
    build_id = resolve_build_id(repo_path, arg)

    info(f"Watching build {BOLD}#{build_id}{RESET}")

    start_epoch = time.time()

    while True:
        build = az_get(f"{BASE_URL}/build/builds/{build_id}?{API_VER}")
        status = build.get("status", "")
        result = build.get("result") or "-"
        branch_name = build.get("sourceBranch", "").removeprefix("refs/heads/")
        requested_by = build.get("requestedFor", {}).get("displayName", "-")
        build_number = build.get("buildNumber", "")

        elapsed = time.time() - start_epoch
        elapsed_fmt = duration_fmt(elapsed)

        try:
            timeline = az_get(f"{BASE_URL}/build/builds/{build_id}/timeline?{API_VER}")
        except Exception:
            timeline = {"records": []}

        trigger = build.get("triggerInfo", {})
        pr_number = trigger.get("pr.number", "")
        pr_sha = trigger.get("pr.sourceSha", "")
        repository = build.get("repository", {})
        repo_slug = repository.get("id", "") if repository.get("type") == "GitHub" else ""
        pr = gh_pr_info(repo_path, pr_number, repo_slug) if pr_number else None

        # Everything above is fetched before clearing, and the whole frame is
        # written at once: a slow API call must never leave a half-drawn screen.
        out = []
        out.append(f"\n{BOLD}Azure DevOps – Build #{build_number}{RESET}  {DIM}(id: {build_id}){RESET}")
        out.append(f"  Branch   {branch_name}")
        out.append(f"  By       {requested_by}")
        out.append(f"  Elapsed  {elapsed_fmt}")
        out.append(f"  Status   {status_icon(status, result)}")

        if pr:
            out.append(f"  PR       {pr_state_line(pr)}")
            pr_head = pr.get("headRefOid") or ""
            if pr_sha and pr_head and pr_sha != pr_head:
                out.append(
                    f"  {YELLOW}⚠{RESET}  this check ran on {pr_sha[:8]}, "
                    f"PR head is now {pr_head[:8]} – it is stale"
                )
            if pr_is_conflicting(pr):
                out.append("")
                out.extend(conflict_warning_lines(pr))

        records = timeline.get("records", [])
        if records:
            out.append(f"\n{BOLD}Timeline:{RESET}")

            parents = {r["id"]: r.get("parentId") for r in records}
            stages = sorted(
                (r for r in records if r.get("type") == "Stage"),
                key=lambda r: r.get("order") or 0,
            )
            for stage in stages:
                stage_id = stage["id"]
                out.append(f"\n  {BOLD}{stage.get('name', '')}{RESET}  {status_icon(stage.get('state', ''), stage.get('result') or '-')}")

                jobs = [
                    r
                    for r in records
                    if r.get("type") == "Job"
                    and (r.get("parentId") == stage_id or parents.get(r.get("parentId")) == stage_id)
                ]
                jobs.sort(key=lambda r: r.get("name", ""))
                for job in jobs:
                    job_dur = ""
                    job_start = job.get("startTime") or ""
                    if job_start:
                        job_start_epoch = _parse_iso(job_start)
                        if job_start_epoch is not None:
                            job_finish = job.get("finishTime") or ""
                            if job_finish and job.get("state") == "completed":
                                job_end_epoch = _parse_iso(job_finish)
                            else:
                                job_end_epoch = time.time()
                            if job_end_epoch is not None:
                                job_dur = duration_fmt(job_end_epoch - job_start_epoch)
                    out.append(
                        f"    {job.get('name', ''):<40} "
                        f"{status_icon(job.get('state', ''), job.get('result') or '-')}  "
                        f"{DIM}{job_dur}{RESET}"
                    )

        out.append("")

        if sys.stdout.isatty():
            subprocess.run(["tput", "clear"])
        print("\n".join(out))

        if status == "completed":
            build_url = f"https://dev.azure.com/{AZURE_ORG}/{AZURE_PROJECT}/_build/results?buildId={build_id}"
            print(f"  {DIM}{build_url}{RESET}\n")

            if result in ("failed", "partiallySucceeded"):
                dump_logs(build_id, timeline, True)

            if show_logs:
                if sys.stdin.isatty() and sys.stdout.isatty():
                    browse_logs(build_id, timeline)
                else:
                    print("--logs ignored: not running in a terminal", file=sys.stderr)

            conflict_note = (
                ", but the pull request conflicts" if pr_is_conflicting(pr) else ""
            )
            if result == "succeeded":
                speak("Build succeeded" + conflict_note)
                sys.exit(0)
            elif result == "partiallySucceeded":
                speak("Build partially succeeded" + conflict_note)
                sys.exit(0)
            elif result == "failed":
                speak("Build failed")
                sys.exit(1)
            elif result == "canceled":
                speak("Build canceled")
                sys.exit(2)
            else:
                sys.exit(3)

        if sys.stdin.isatty() and sys.stdout.isatty():
            info(f"Next poll in {POLL_INTERVAL}s  (Ctrl-C to abort, 'l' + Enter to view logs)")
            ready, _, _ = select.select([sys.stdin], [], [], POLL_INTERVAL)
            if ready and sys.stdin.readline().strip().lower() == "l":
                browse_logs(build_id, timeline)
        else:
            info(f"Next poll in {POLL_INTERVAL}s  (Ctrl-C to abort)")
            time.sleep(POLL_INTERVAL)


def _parse_iso(timestamp):
    try:
        cleaned = timestamp.replace("Z", "+00:00")
        if "." in cleaned:
            head, tail = cleaned.split(".", 1)
            frac, _, tz = tail.partition("+")
            tz = "+" + tz if tz else ""
            cleaned = f"{head}.{frac[:6]}{tz}"
        import datetime

        return datetime.datetime.fromisoformat(cleaned).timestamp()
    except (ValueError, AttributeError):
        return None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except requests.RequestException as exc:
        die(f"HTTP request failed: {exc}")
