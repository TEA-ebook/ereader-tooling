# jira_log_bucket

Log time on a Jira ticket and take the same amount off the remaining estimate of a bucket ticket.

```sh
export JIRA_USER=you@vivlio.com
export JIRA_TOKEN=...   # https://id.atlassian.com/manage-profile/security/api-tokens

jira_log_bucket      # asks for each value
jira_log_bucket -n   # dry run: show what would be done, change nothing

# Or give the values on the command line (missing values are asked)
jira_log_bucket LIS-123 LIS-42 1h --date 2026-11-24 --at 16:30 -t Maintenance -m "Investigate crash"
jira_log_bucket 123 42 45m --now -n
```

Options: `-t`/`--track` (`Maintenance`, `Feature`, `Service` or `1`-`3`), `--now` (the work ends now), `--date YYYY-MM-DD`, `--at HH:MM`, `-m COMMENT`, `-n` (dry run), `-f` (accept a bucket title that does not start with "Bucket"), `-y` (do not ask for the final confirmation).
If you do not give `--now` or `--date`, the script asks for the day of the work. Press Enter to use today.
You cannot use `--now` with `--date` or `--at`.
If you give bug, bucket and duration on the command line, the script does not ask for the comment. The default comment is none.
In that case, the script asks for the end time only for a past day without `--at`. For today, the default end time is now.
If you do not give `-t`, the script asks for the track.

Example session (1h of work ending at 16:30: worklog 15:30 -> 16:30 on LIS-123, bucket LIS-42 loses 1h):

```
Bug ticket: 123
  LIS-123 "Crash when opening a book" (2h logged)
Track of LIS-123 (current: Feature):
  1. Maintenance  Sujet remonté par autres équipes avec sponsor + bugs identifiés en prod (hors test interne)
  2. Feature      Bug identifié sur une phase de test interne
  3. Service      Retours et demandes clients (bug), facturé aux clients
Choice [1-3, empty = keep Feature]: 1
Bucket ticket (empty = LIS-42): 
  LIS-42 "Bucket bugs November" (12h remaining)
Duration (1h, 30m, 1h30m, 1.5): 1h
Day of the work (YYYY-MM-DD, empty = today): 
End time of the work today (HH:MM, empty = now): 16:30
Comment (empty = none): Investigate crash

Log 1h on LIS-123 "Crash when opening a book" (2026-11-09 15:30 -> 16:30)
Comment: Investigate crash
Track: Feature -> Maintenance
Bucket LIS-42 "Bucket bugs November": 12h -> 11h remaining
Proceed? [y/N] y
Done
```

- The script shows each ticket title as soon as you enter it.
- If an answer is invalid, the script asks the question again.
- The script shows the track rules and asks for the track of the bug ticket. Press Enter to keep the current track.
- You must confirm with `y` before the script writes to Jira.
- The script refuses an epic as the bug ticket. Time is never logged on an epic.
- The total time logged on the bug ticket (existing worklogs + this one) cannot exceed 10h.
- The script saves the last bucket ticket in `~/.local/state/jira_log_bucket/last_bucket` (or `$XDG_STATE_HOME/jira_log_bucket/last_bucket`). Press Enter at the bucket question to use it again.
- If the bucket ticket title does not start with "Bucket", the script asks if you want to use it anyway. Use `-f` to skip this question.
- If a command line value is invalid, the script shows the error and asks for that value.
- Tickets: `1234`, `LIS-1234` or a full browse URL.
- Duration: `1h`, `30m`, `1h30m`, or a number of hours (`1.5`).
- If the bucket goes below zero, its remaining estimate is set to 0 and a warning is printed.
