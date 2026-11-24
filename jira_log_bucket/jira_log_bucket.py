#!/usr/bin/env python3
"""Log time on a Jira ticket and take the same amount off a bucket ticket.

Usage:
  jira_log_bucket.py [bug] [bucket] [duration] [-t TRACK] [--now | --date YYYY-MM-DD [--at HH:MM]]
                     [-m COMMENT] [-n] [-f] [-y]

  bug        ticket that receives the worklog (1234, LIS-1234 or a browse URL), never an epic
  bucket     ticket whose remaining estimate is decremented (same formats)
  duration   time spent: 1h, 30m, 1h30m, or a plain number of hours (1.5)
  -t         track of the bug ticket: Maintenance, Feature, Service or 1-3
  --now      the work ends now (today, current time); not allowed with --date or --at
  --date     day of the work; without --now or --date, the day is asked (empty = today)
  --at       end time of the work (HH:MM or 16h30); asked for a past day
  -m         worklog comment
  -n         dry run: print what would be done, change nothing
  -f         allow a bucket ticket whose title does not start with "Bucket"
  -y         do not ask for the final confirmation

  Each value missing from the command line is asked interactively; an invalid
  value is asked again. The day is asked if neither --now nor --date is given.
  The comment is asked only if bug, bucket or duration is missing. The end time
  is asked if bug, bucket or duration is missing, or if the day is in the past
  and --at is not given. The track is asked if -t is not given.
  The ticket titles are shown as soon as they are known, and you must confirm
  before anything is written to Jira.

  If the bucket title does not start with "Bucket", you must confirm that
  you want to use it anyway (or pass -f).

  The last bucket used is saved in $XDG_STATE_HOME/jira_log_bucket/last_bucket
  (default ~/.local/state/...). Press Enter at the bucket question to use it again.

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
STATE_FILE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                          "jira_log_bucket", "last_bucket")
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


def work_date(value):
    try:
        day = datetime.date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"invalid date: {value!r} (expected YYYY-MM-DD)") from None
    if day > datetime.date.today():
        raise ValueError(f"date is in the future: {value!r}")
    return day


def work_day(value):
    """Parse the day of the work; empty or today gives None (today)."""
    day = work_date(value) if value.strip() else None
    return None if day == datetime.date.today() else day


def end_time(value, day=None):
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    if not value.strip():
        if day is not None and day != now.date():
            raise ValueError("an end time is required for a past date")
        return now.astimezone()
    m = re.fullmatch(r"(\d{1,2})[:hH](\d{2})?", value.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise ValueError(f"invalid time: {value!r} (expected HH:MM or 16h30)")
    base = now if day is None else datetime.datetime.combine(day, now.time())
    # astimezone() after the date is set, so a past day across a DST change gets its own offset
    return base.replace(hour=int(m.group(1)), minute=int(m.group(2) or 0)).astimezone()


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


def ask(prompt, parse, initial=None):
    """Ask until parse() accepts the answer; parse raises ValueError to ask again.

    If initial (a command line value) is given, try it first and only ask if it is invalid."""
    if initial is not None:
        try:
            return parse(initial)
        except ValueError as e:
            print(f"  {e}", file=sys.stderr)
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


def ask_bug(initial=None):
    def parse(value):
        key, issue = fetch_issue(value, f"summary,timetracking,issuetype,{TRACK_FIELD}")
        issue_type = issue["fields"].get("issuetype") or {}
        if issue_type.get("hierarchyLevel", 0) >= 1 or issue_type.get("name", "").lower() == "epic":
            raise ValueError(f"{key} is an epic, time is never logged on an epic")
        spent =(issue["fields"].get("timetracking") or {}).get("timeSpentSeconds") or 0
        print(f"  {key} \"{issue['fields']['summary']}\" ({fmt_duration(spent)} logged)")
        if spent + 60 > MAX_TICKET_SECONDS:
            raise ValueError(f"{key} already has {fmt_duration(spent)} logged, "
                             f"the limit is {fmt_duration(MAX_TICKET_SECONDS)} per ticket")
        return key, issue, spent
    return ask("Bug ticket: ", parse, initial)


def track_name(value):
    """Accept a track number (1-3) or name (case-insensitive)."""
    value = value.strip()
    if value.isdigit() and 1 <= int(value) <= len(TRACKS):
        return TRACKS[int(value) - 1][0]
    for name, _ in TRACKS:
        if value.lower() == name.lower():
            return name
    raise ValueError(f"invalid track: {value!r} (expected 1-{len(TRACKS)} or "
                     f"{', '.join(name for name, _ in TRACKS)})")


def ask_track(bug_key, current, initial=None):
    """Return the chosen track name; the current one is kept on an empty answer."""
    if initial is not None:
        try:
            return track_name(initial)
        except ValueError as e:
            print(f"  {e}", file=sys.stderr)
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
        return track_name(value)
    keep = f", empty = keep {current}" if current else ""
    return ask(f"Choice [1-{len(TRACKS)}{keep}]: ", parse)


def load_last_bucket():
    try:
        with open(STATE_FILE) as f:
            return issue_key(f.read())
    except (OSError, ValueError):
        return None


def save_last_bucket(key):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            f.write(key + "\n")
    except OSError as e:
        print(f"Warning: could not save the last bucket to {STATE_FILE}: {e}", file=sys.stderr)


def ask_bucket(initial=None, force=False):
    last = load_last_bucket()

    def parse(value):
        if not value.strip():
            if not last:
                raise ValueError("enter a bucket ticket")
            value = last
        key, issue = fetch_issue(value)
        title = issue["fields"]["summary"]
        remaining = (issue["fields"].get("timetracking") or {}).get("remainingEstimateSeconds")
        left = "no remaining estimate" if remaining is None else f"{fmt_duration(remaining)} remaining"
        print(f"  {key} \"{title}\" ({left})")
        if not title.strip().lower().startswith("bucket"):
            if force:
                print("  Warning: this title does not start with \"Bucket\" (forced)", file=sys.stderr)
            elif not confirm("  This title does not start with \"Bucket\". Use it anyway?"):
                raise ValueError("enter another bucket ticket")
        return key, issue
    prompt = f"Bucket ticket (empty = {last}): " if last else "Bucket ticket: "
    return ask(prompt, parse, initial)


def ask_duration(bug_key, already_spent, initial=None):
    def parse(value):
        seconds = duration_seconds(value)
        if already_spent + seconds > MAX_TICKET_SECONDS:
            raise ValueError(f"{bug_key} already has {fmt_duration(already_spent)} logged; adding "
                             f"{fmt_duration(seconds)} would exceed the {fmt_duration(MAX_TICKET_SECONDS)} "
                             f"limit (at most {fmt_duration(MAX_TICKET_SECONDS - already_spent)} left)")
        return seconds
    return ask("Duration (1h, 30m, 1h30m, 1.5): ", parse, initial)


def main():
    parser = argparse.ArgumentParser(
        description="Log time on a ticket and decrement a bucket ticket. Missing values are asked interactively.")
    parser.add_argument("bug", nargs="?", help="ticket to log time on")
    parser.add_argument("bucket", nargs="?", help="bucket ticket to decrement")
    parser.add_argument("duration", nargs="?", help="1h, 30m, 1h30m or hours (1.5)")
    parser.add_argument("-t", "--track", help="track of the bug ticket: Maintenance, Feature, Service or 1-3")
    parser.add_argument("--now", action="store_true", help="the work ends now (today, current time)")
    parser.add_argument("--date", help="day of the work (YYYY-MM-DD), asked if neither --now nor --date is given")
    parser.add_argument("--at", help="end time of the work (HH:MM)")
    parser.add_argument("-m", "--comment", help="worklog comment")
    parser.add_argument("-n", "--dry-run", action="store_true", help="print what would be done, change nothing")
    parser.add_argument("-f", "--force", action="store_true",
                        help="allow a bucket whose title does not start with \"Bucket\"")
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask for the final confirmation")
    args = parser.parse_args()

    if not os.environ.get("JIRA_USER") or not os.environ.get("JIRA_TOKEN"):
        die(f"JIRA_USER and JIRA_TOKEN must be set\nCreate a token at {TOKEN_URL}")

    if args.now and (args.date is not None or args.at is not None):
        die("--now cannot be used with --date or --at")
    day = None
    if args.date is not None:
        try:
            day = work_day(args.date)
        except ValueError as e:
            die(str(e))

    # Jira answers 404 for unauthenticated issue requests, so check the credentials first
    try:
        jira("GET", "/rest/api/3/myself")
    except RuntimeError as e:
        die(f"Jira authentication failed; check JIRA_USER and JIRA_TOKEN\n{e}\nCreate a new token at {TOKEN_URL}")

    # With bug, bucket and duration on the command line, -m (and --at for today) keep their defaults
    interactive = None in (args.bug, args.bucket, args.duration)

    bug_key, bug, already_spent = ask_bug(args.bug)
    old_track = (bug["fields"].get(TRACK_FIELD) or {}).get("value")
    track = ask_track(bug_key, old_track, args.track)
    bucket_key, bucket = ask_bucket(args.bucket, args.force)
    duration = ask_duration(bug_key, already_spent, args.duration)
    if not args.now and args.date is None:
        day = ask("Day of the work (YYYY-MM-DD, empty = today): ", work_day)
    if args.now:
        at = ""
    elif args.at is not None or interactive or day is not None:
        at = args.at
    else:
        at = ""
    if day is None:
        end = ask("End time of the work today (HH:MM, empty = now): ", end_time, at)
    else:
        end = ask(f"End time of the work on {day} (HH:MM): ", lambda value: end_time(value, day), at)
    if args.comment is not None or not interactive:
        comment = (args.comment or "").strip()
    else:
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
    if not args.yes and not confirm("Proceed?"):
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

    save_last_bucket(bucket_key)
    print("Done")


if __name__ == "__main__":
    main()
