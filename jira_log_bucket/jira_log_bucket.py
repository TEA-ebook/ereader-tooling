#!/usr/bin/env python3
"""Log time on a Jira ticket and take the same amount off a bucket ticket.

Usage:
  jira_log_bucket.py <bug> <bucket> <duration> [--at HH:MM] [-m COMMENT] [-n] [-f]

  bug        ticket that receives the worklog (1234, LIS-1234 or a browse URL)
  bucket     ticket whose remaining estimate is decremented (same formats)
  duration   time spent: 1h, 30m, 1h30m, or a plain number of hours (1.5)
  --at       end time of the work today (HH:MM or 16h30), default: now
  -m         worklog comment
  -n         dry run: print what would be done, change nothing
  -f         allow a bucket ticket whose title does not start with "Bucket"

  The ticket titles and the planned changes are shown first, and you must
  confirm before anything is written to Jira.

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


def die(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def issue_key(value):
    m = re.search(rf"{PROJECT_PREFIX}-(\d+)", value, re.IGNORECASE)
    if m:
        return f"{PROJECT_PREFIX}-{m.group(1)}"
    if value.isdigit():
        return f"{PROJECT_PREFIX}-{value}"
    raise argparse.ArgumentTypeError(f"invalid ticket id: {value}")


def duration_seconds(value):
    v = value.strip().lower()
    try:
        seconds = round(float(v) * 3600)
    except ValueError:
        m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?\s*(?:(\d+)m)?", v)
        if not m or not any(m.groups()):
            raise argparse.ArgumentTypeError(f"invalid duration: {value}")
        seconds = round(float(m.group(1) or 0) * 3600) + int(m.group(2) or 0) * 60
    if seconds < 60:
        raise argparse.ArgumentTypeError(f"duration must be at least 1m: {value}")
    return seconds


def end_time(value):
    m = re.fullmatch(r"(\d{1,2})[:hH](\d{2})?", value.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise argparse.ArgumentTypeError(f"invalid time: {value}")
    now = datetime.datetime.now().astimezone()
    return now.replace(hour=int(m.group(1)), minute=int(m.group(2) or 0), second=0, microsecond=0)


def fmt_duration(seconds):
    sign = "-" if seconds < 0 else ""
    h, m = divmod(abs(seconds) // 60, 60)
    if h and m:
        return f"{sign}{h}h{m:02d}m"
    return f"{sign}{h}h" if h else f"{sign}{m}m"


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


def main():
    parser = argparse.ArgumentParser(description="Log time on a ticket and decrement a bucket ticket.")
    parser.add_argument("bug", type=issue_key, help="ticket to log time on")
    parser.add_argument("bucket", type=issue_key, help="bucket ticket to decrement")
    parser.add_argument("duration", type=duration_seconds, help="1h, 30m, 1h30m or hours (1.5)")
    parser.add_argument("--at", type=end_time, help="end time of the work today (HH:MM), default: now")
    parser.add_argument("-m", "--comment", help="worklog comment")
    parser.add_argument("-n", "--dry-run", action="store_true", help="print what would be done")
    parser.add_argument("-f", "--force", action="store_true", help="allow a bucket whose title does not start with \"Bucket\"")
    args = parser.parse_args()

    if not os.environ.get("JIRA_USER") or not os.environ.get("JIRA_TOKEN"):
        die(f"JIRA_USER and JIRA_TOKEN must be set\nCreate a token at {TOKEN_URL}")

    # Jira answers 404 for unauthenticated issue requests, so check the credentials first
    try:
        jira("GET", "/rest/api/3/myself")
    except RuntimeError as e:
        die(f"Jira authentication failed; check JIRA_USER and JIRA_TOKEN\n{e}\nCreate a new token at {TOKEN_URL}")

    end = args.at or datetime.datetime.now().astimezone().replace(second=0, microsecond=0)
    start = end - datetime.timedelta(seconds=args.duration)
    spent = fmt_duration(args.duration)

    try:
        bug = jira("GET", f"/rest/api/3/issue/{args.bug}?fields=summary,timetracking")
        bucket = jira("GET", f"/rest/api/3/issue/{args.bucket}?fields=summary,timetracking")
    except RuntimeError as e:
        die(str(e))

    bucket_title = bucket["fields"]["summary"]
    if not bucket_title.strip().lower().startswith("bucket"):
        if not args.force:
            die(f"{args.bucket} \"{bucket_title}\" does not look like a bucket (title does not start with "
                "\"Bucket\"); use -f/--force to use it anyway")
        print(f"Warning: {args.bucket} title does not start with \"Bucket\" (forced)", file=sys.stderr)

    already_spent = (bug["fields"].get("timetracking") or {}).get("timeSpentSeconds") or 0
    if already_spent + args.duration > MAX_TICKET_SECONDS:
        die(f"{args.bug} already has {fmt_duration(already_spent)} logged; adding {fmt_duration(args.duration)} "
            f"would exceed the {fmt_duration(MAX_TICKET_SECONDS)} limit per ticket")

    tracking = bucket["fields"].get("timetracking") or {}
    remaining = tracking.get("remainingEstimateSeconds")
    if remaining is None:
        print(f"Warning: {args.bucket} has no remaining estimate; it will start from 0", file=sys.stderr)
        remaining = 0
    new_remaining = remaining - args.duration
    if new_remaining < 0:
        print(f"Warning: bucket {args.bucket} is over budget by {fmt_duration(-new_remaining)}; "
              "remaining estimate set to 0", file=sys.stderr)

    print(f"Log {spent} on {args.bug} \"{bug['fields']['summary']}\" "
          f"({start:%Y-%m-%d %H:%M} -> {end:%H:%M})")
    print(f"Bucket {args.bucket} \"{bucket['fields']['summary']}\": "
          f"{fmt_duration(remaining)} -> {fmt_duration(max(0, new_remaining))} remaining")
    if args.dry_run:
        print("Dry run: nothing changed")
        return
    try:
        answer = input("Proceed? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("Aborted: nothing changed")
        sys.exit(1)

    worklog = {
        "started": start.strftime("%Y-%m-%dT%H:%M:%S.000%z"),
        "timeSpentSeconds": args.duration,
    }
    if args.comment:
        worklog["comment"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": args.comment}]}],
        }
    try:
        created = jira("POST", f"/rest/api/3/issue/{args.bug}/worklog", worklog)
    except RuntimeError as e:
        die(str(e))

    # Resend the original estimate, otherwise Jira may clear it when only the remaining one is edited
    edit = {"remainingEstimate": f"{max(0, new_remaining) // 60}m"}
    if tracking.get("originalEstimate"):
        edit["originalEstimate"] = tracking["originalEstimate"]
    try:
        jira("PUT", f"/rest/api/3/issue/{args.bucket}", {"update": {"timetracking": [{"edit": edit}]}})
    except RuntimeError as e:
        die(f"worklog {created['id']} was created on {args.bug}, but the bucket was not updated:\n{e}\n"
            f"Reduce the remaining estimate of {args.bucket} by {spent} by hand.")

    print("Done")


if __name__ == "__main__":
    main()
