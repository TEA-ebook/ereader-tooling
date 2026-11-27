# create-branch-from-jira

Create and check out a git branch named after a Jira ticket.

```sh
export JIRA_USER=you@vivlio.com
export JIRA_TOKEN=...   # https://id.atlassian.com/manage-profile/security/api-tokens

# All three are the same ticket
create-branch-from-jira 1234
create-branch-from-jira LIS-1234
create-branch-from-jira https://tea-ebook.atlassian.net/browse/LIS-1234
# -> git checkout -b bugfix/LIS-1234-reader-crashes-on-open
```

- Branch name: `<type>/LIS-<id>-<slug>`. The slug is the ticket summary in lower case. Text in parentheses is removed, accents are removed (`é` -> `e`), and other characters are replaced with `-`. The slug is 60 characters maximum. The script checks the final name with `git check-ref-format`.
- The type is one of `feature`, `bugfix`, `hotfix`, `refacto`, `misc`. The script finds it in this order:
  1. A ticket label with the same name as the type.
  2. The issue type:

     | Issue type | Branch type |
     |---|---|
     | Bug | `bugfix` |
     | Story, New Feature, Improvement, Epic | `feature` |
     | Hotfix | `hotfix` |
     | Refactor, Refactoring | `refacto` |
     | Task, Sub-task | `misc` |

  3. If there is no match, you select the type with `fzf` (or a numbered menu if `fzf` is not installed).
- After the branch is created, the script asks if you want to take the ticket (`[Y/n]`). If you answer yes, it assigns the ticket to you and moves it to "En cours" (In progress). The script does not ask if the ticket is already yours and in progress.
- Requires `curl`, `python3` and `git`. `fzf` is optional.
- The script checks your credentials first, because Jira returns 404 (not 401) for unauthenticated issue requests.
