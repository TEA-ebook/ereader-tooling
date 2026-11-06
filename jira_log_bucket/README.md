# jira_log_bucket

Log time on a Jira ticket and take the same amount off the remaining estimate of a bucket ticket.

```sh
export JIRA_USER=you@vivlio.com
export JIRA_TOKEN=...   # https://id.atlassian.com/manage-profile/security/api-tokens

# 1h of work ending at 16:30: worklog 15:30 -> 16:30 on LIS-123, bucket LIS-42 loses 1h
./jira_log_bucket.py LIS-123 LIS-42 1h --at 16:30

# Work ending now, with a comment
./jira_log_bucket.py 123 42 1h30m -m "Investigate crash"

# Show what would be done without changing anything
./jira_log_bucket.py 123 42 45m -n
```

- The ticket titles and planned changes are shown, and you must confirm with `y` before anything is written.
- The total time logged on the bug ticket (existing worklogs + this one) cannot exceed 10h.
- The bucket ticket title must start with "Bucket". Use `-f`/`--force` to use another ticket anyway.
- Tickets: `1234`, `LIS-1234` or a full browse URL.
- Duration: `1h`, `30m`, `1h30m`, or a number of hours (`1.5`).
- If the bucket goes below zero, its remaining estimate is set to 0 and a warning is printed.
