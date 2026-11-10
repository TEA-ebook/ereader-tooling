#!/usr/bin/env python3
"""Log time on a Jira ticket and take the same amount off a bucket ticket.

Usage:
  jira_log_bucket.py [-n]

  -n         dry run: print what would be done, change nothing

  The script asks for each value in turn:
    bug ticket     ticket that receives the worklog (1234, LIS-1234 or a browse URL)
    track          track of the bug ticket, chosen from the rules shown (empty: keep it)
    bucket ticket  ticket whose remaining estimate is decremented (same formats)
    duration       time spent: 1h, 30m, 1h30m, or a plain number of hours (1.5)
    end time       end time of the work today (HH:MM or 16h30), empty: now
    comment        worklog comment, empty: no comment

  An invalid answer is asked again. The ticket titles are shown as soon as
  they are entered, and you must confirm before anything is written to Jira.

  If the bucket title does not start with "Bucket", you must confirm that
  you want to use it anyway.

  The total time logged on the bug ticket (all users, existing worklogs +
  this one) cannot exceed 10h. There is no way to bypass this limit.

  Example: logging 1h on LIS-123 at 16:30 creates a worklog from 15:30 to
  16:30 on LIS-123 and reduces the bucket's remaining estimate by 1h.

Required env vars:
  JIRA_USER   your Atlassian account email
  JIRA_TOKEN  your Atlassian API token
              (https://id.atlassian.com/manage-profile/security/api-tokens)
"""

import argparse
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE_URL = "https://tea-ebook.atlassian.net"
PROJECT_PREFIX = "LIS"
TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"
MAX_TICKET_SECONDS = 10 * 3600
TRACK_FIELD = "customfield_11912"
TRACKS = [
    ("Maintenance", "Sujet remonté par autres équipes avec sponsor + bugs identifiés en prod (hors test interne)"),
    ("Feature", "Bug identifié sur une phase de test interne"),
    ("Service", "Retours et demandes clients (bug), facturé aux clients"),
]


def die(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def issue_key(value):
    value = value.strip()
    m = re.search(rf"{PROJECT_PREFIX}-(\d+)", value, re.IGNORECASE)
    if m:
        return f"{PROJECT_PREFIX}-{m.group(1)}"
    if value.isdigit():
        return f"{PROJECT_PREFIX}-{value}"
    raise ValueError(f"invalid ticket id: {value!r} (expected 1234, {PROJECT_PREFIX}-1234 or a browse URL)")


def duration_seconds(value):
    v = value.strip().lower()
    try:
        seconds = round(float(v) * 3600)
    except ValueError:
        m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?\s*(?:(\d+)m)?", v)
        if not m or not any(m.groups()):
            raise ValueError(f"invalid duration: {value!r} (expected 1h, 30m, 1h30m or 1.5)") from None
        seconds = round(float(m.group(1) or 0) * 3600) + int(m.group(2) or 0) * 60
    if seconds < 60:
        raise ValueError(f"duration must be at least 1m: {value!r}")
    return seconds


def end_time(value):
    now = datetime.datetime.now().astimezone().replace(second=0, microsecond=0)
    if not value.strip():
        return now
    m = re.fullmatch(r"(\d{1,2})[:hH](\d{2})?", value.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise ValueError(f"invalid time: {value!r} (expected HH:MM or 16h30)")
    return now.replace(hour=int(m.group(1)), minute=int(m.group(2) or 0))


def fmt_duration(seconds):
    sign = "-" if seconds < 0 else ""
    h, m = divmod(abs(seconds) // 60, 60)
    if h and m:
        return f"{sign}{h}h{m:02d}m"
    return f"{sign}{h}h" if h else f"{sign}{m}m"


def read_line(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print("\nAborted: nothing changed")
        sys.exit(1)


def ask(prompt, parse):
    """Ask until parse() accepts the answer; parse raises ValueError to ask again."""
    while True:
        try:
            return parse(read_line(prompt))
        except ValueError as e:
            print(f"  {e}", file=sys.stderr)


def confirm(prompt):
    return read_line(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def jira(method, path, body=None):
    auth = base64.b64encode(f"{os.environ['JIRA_USER']}:{os.environ['JIRA_TOKEN']}".encode()).decode()
    req = urllib.request.Request(
        BASE_URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            return json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            d = json.loads(detail)
            detail = "; ".join(d.get("errorMessages", []) + [f"{k}: {v}" for k, v in d.get("errors", {}).items()]) or detail
        except ValueError:
            pass
        raise RuntimeError(f"{method} {path} failed (HTTP {e.code}): {detail}") from None


def fetch_issue(value, fields="summary,timetracking"):
    """Parse a ticket id and fetch it; any problem raises ValueError so the question is asked again."""
    key = issue_key(value)
    try:
        issue = jira("GET", f"/rest/api/3/issue/{key}?fields={fields}")
    except RuntimeError as e:
        raise ValueError(str(e)) from None
    return key, issue


def ask_bug():
    def parse(value):
        key, issue = fetch_issue(value, f"summary,timetracking,{TRACK_FIELD}")
        spent = (issue["fields"].get("timetracking") or {}).get("timeSpentSeconds") or 0
        print(f"  {key} \"{issue['fields']['summary']}\" ({fmt_duration(spent)} logged)")
        if spent + 60 > MAX_TICKET_SECONDS:
            raise ValueError(f"{key} already has {fmt_duration(spent)} logged, "
                             f"the limit is {fmt_duration(MAX_TICKET_SECONDS)} per ticket")
        return key, issue, spent
    return ask("Bug ticket: ", parse)


def ask_track(bug_key, current):
    """Return the chosen track name; the current one is kept on an empty answer."""
    print(f"Track of {bug_key} (current: {current or 'none'}):")
    width = max(len(name) for name, _ in TRACKS)
    for i, (name, rule) in enumerate(TRACKS, 1):
        print(f"  {i}. {name:<{width}}  {rule}")

    def parse(value):
        value = value.strip()
        if not value:
            if current:
                return current
            raise ValueError("this ticket has no track, choose one")
        if value.isdigit() and 1 <= int(value) <= len(TRACKS):
            return TRACKS[int(value) - 1][0]
        raise ValueError(f"enter a number from 1 to {len(TRACKS)}")
    keep = f", empty = keep {current}" if current else ""
    return ask(f"Choice [1-{len(TRACKS)}{keep}]: ", parse)


def ask_bucket():
    def parse(value):
        key, issue = fetch_issue(value)
        title = issue["fields"]["summary"]
        remaining = (issue["fields"].get("timetracking") or {}).get("remainingEstimateSeconds")
        left = "no remaining estimate" if remaining is None else f"{fmt_duration(remaining)} remaining"
        print(f"  {key} \"{title}\" ({left})")
        if not title.strip().lower().startswith("bucket") and not confirm(
                "  This title does not start with \"Bucket\". Use it anyway?"):
            raise ValueError("enter another bucket ticket")
        return key, issue
    return ask("Bucket ticket: ", parse)


def ask_duration(bug_key, already_spent):
    def parse(value):
        seconds = duration_seconds(value)
        if already_spent + seconds > MAX_TICKET_SECONDS:
            raise ValueError(f"{bug_key} already has {fmt_duration(already_spent)} logged; adding "
                             f"{fmt_duration(seconds)} would exceed the {fmt_duration(MAX_TICKET_SECONDS)} "
                             f"limit (at most {fmt_duration(MAX_TICKET_SECONDS - already_spent)} left)")
        return seconds
    return ask("Duration (1h, 30m, 1h30m, 1.5): ", parse)


def main():
    parser = argparse.ArgumentParser(
        description="Log time on a ticket and decrement a bucket ticket. All values are asked interactively.")
    parser.add_argument("-n", "--dry-run", action="store_true", help="print what would be done, change nothing")
    args = parser.parse_args()

    if not os.environ.get("JIRA_USER") or not os.environ.get("JIRA_TOKEN"):
        die(f"JIRA_USER and JIRA_TOKEN must be set\nCreate a token at {TOKEN_URL}")

    # Jira answers 404 for unauthenticated issue requests, so check the credentials first
    try:
        jira("GET", "/rest/api/3/myself")
    except RuntimeError as e:
        die(f"Jira authentication failed; check JIRA_USER and JIRA_TOKEN\n{e}\nCreate a new token at {TOKEN_URL}")

    bug_key, bug, already_spent = ask_bug()
    old_track = (bug["fields"].get(TRACK_FIELD) or {}).get("value")
    track = ask_track(bug_key, old_track)
    bucket_key, bucket = ask_bucket()
    duration = ask_duration(bug_key, already_spent)
    end = ask("End time of the work today (HH:MM, empty = now): ", end_time)
    comment = read_line("Comment (empty = none): ").strip()

    start = end - datetime.timedelta(seconds=duration)
    spent = fmt_duration(duration)

    tracking = bucket["fields"].get("timetracking") or {}
    remaining = tracking.get("remainingEstimateSeconds")
    if remaining is None:
        print(f"Warning: {bucket_key} has no remaining estimate; it will start from 0", file=sys.stderr)
        remaining = 0
    new_remaining = remaining - duration
    if new_remaining < 0:
        print(f"Warning: bucket {bucket_key} is over budget by {fmt_duration(-new_remaining)}; "
              "remaining estimate set to 0", file=sys.stderr)

    print()
    print(f"Log {spent} on {bug_key} \"{bug['fields']['summary']}\" "
          f"({start:%Y-%m-%d %H:%M} -> {end:%H:%M})")
    if comment:
        print(f"Comment: {comment}")
    if track == old_track:
        print(f"Track: {track} (unchanged)")
    else:
        print(f"Track: {old_track or 'none'} -> {track}")
    print(f"Bucket {bucket_key} \"{bucket['fields']['summary']}\": "
          f"{fmt_duration(remaining)} -> {fmt_duration(max(0, new_remaining))} remaining")
    if args.dry_run:
        print("Dry run: nothing changed")
        return
    if not confirm("Proceed?"):
        print("Aborted: nothing changed")
        sys.exit(1)

    if track != old_track:
        try:
            jira("PUT", f"/rest/api/3/issue/{bug_key}", {"fields": {TRACK_FIELD: {"value": track}}})
        except RuntimeError as e:
            die(f"could not set the track of {bug_key}, nothing changed:\n{e}")

    worklog = {
        "started": start.strftime("%Y-%m-%dT%H:%M:%S.000%z"),
        "timeSpentSeconds": duration,
    }
    if comment:
        worklog["comment"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}],
        }
    try:
        created = jira("POST", f"/rest/api/3/issue/{bug_key}/worklog", worklog)
    except RuntimeError as e:
        changed = f" (the track of {bug_key} was already set to {track})" if track != old_track else ""
        die(f"{e}{changed}")

    # Resend the original estimate, otherwise Jira may clear it when only the remaining one is edited
    edit = {"remainingEstimate": f"{max(0, new_remaining) // 60}m"}
    if tracking.get("originalEstimate"):
        edit["originalEstimate"] = tracking["originalEstimate"]
    try:
        jira("PUT", f"/rest/api/3/issue/{bucket_key}", {"update": {"timetracking": [{"edit": edit}]}})
    except RuntimeError as e:
        die(f"worklog {created['id']} was created on {bug_key}, but the bucket was not updated:\n{e}\n"
            f"Reduce the remaining estimate of {bucket_key} by {spent} by hand.")

    print("Done")


if __name__ == "__main__":
    main()
