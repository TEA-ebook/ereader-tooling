# open-jira-ticket

Open a Jira ticket in the browser. Bind the script to a keyboard shortcut in your desktop environment.

```sh
open-jira-ticket
```

1. The script reads the clipboard (with `xclip`).
2. A dialog asks for the ticket. The script uses `zenity`, then `kdialog`, then `xterm`. If the clipboard contains a ticket, the dialog shows its key. Press Enter to open it, or type a different ticket.
3. The script opens `https://tea-ebook.atlassian.net/browse/<KEY>` in the browser.

Accepted input:

| Input | Opens |
|---|---|
| `1234` | `LIS-1234` |
| `LIS-1234`, `lis-1234` | `LIS-1234` |
| `BNB-42`, `RDR-7` (any project) | `BNB-42`, `RDR-7` |
| `https://tea-ebook.atlassian.net/browse/RDR-7` | `RDR-7` |

A bare number is a ticket of the `LIS` project (`DEFAULT_PROJECT` in the script). The script does not keep a list of the other projects. Any `<PROJECT>-<number>` key is accepted.

## KDE shortcut

1. Run `./setup.sh` at the root of the repo.
2. Open **System Settings > Shortcuts > Custom Shortcuts**.
3. Add a **Command/URL** action with the command `open-jira-ticket` (or the full path to the script).
4. Set the trigger key, for example `Meta+Shift+A`.
