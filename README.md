# ereader-tooling
Aims to regroup useful personal tooling to share with e-reader team

## Install

Symlink the tool scripts into a folder in your `PATH`. Each link has the name of its tool folder (for example `poll` runs `poll/poll_ci.py`):

```sh
./setup.sh           # links in ~/.local/bin
./setup.sh ~/bin     # links in another folder
./setup.sh -u        # remove the links
```

Existing files that are not symlinks are not overwritten. Run the script again after you add a tool.

## Tools

- [sn_switcher](sn_switcher/) - Switch the device serial number in `~/qboo/private/prod/sn` from a list of named serials.
- [poll](poll/) - Poll an Azure DevOps pipeline build until it completes.
- [qt_doc_version_switcher](qt_doc_version_switcher/) - Userscript that redirects doc.qt.io pages to your preferred Qt version (6.8 by default) and adds a floating version switcher.
- [jira_log_bucket](jira_log_bucket/) - Log time on a Jira ticket and decrement the remaining estimate of a bucket ticket.
- [create-branch-from-jira](create-branch-from-jira/) - Create and check out a git branch named after a Jira ticket (`<type>/<PROJECT>-<id>-<summary>`).
- [open-jira-ticket](open-jira-ticket/) - Open a Jira ticket of any project (`1234`, `LIS-1234`, `BNB-42`, browse URL) from the selected text or a prompt. Bind it to a keyboard shortcut.
