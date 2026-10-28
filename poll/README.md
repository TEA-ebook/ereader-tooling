# poll

Polls an Azure DevOps pipeline build until it completes, then reports the result (and speaks it with `espeak-ng` if installed).

```sh
poll_ci.py                # latest build for the current git branch
poll_ci.py my-branch      # latest build for a branch (push builds, then PR builds)
poll_ci.py 12345          # a build ID
poll_ci.py -C ~/qboo      # use another repo for branch/commit lookups
poll_ci.py -l             # browse task logs (fzf or menu) when the build completes
```

While the build runs, type `l` + Enter to browse task logs. Failing task log tails are printed automatically. If `gh` is authenticated, the script also flags a conflicting or stale pull request.

Requires Python 3 with `requests`, and these env vars:

| Variable            | Description                                                  |
| ------------------- | ------------------------------------------------------------ |
| `AZURE_ORG`         | Organisation name (required)                                 |
| `AZURE_PROJECT`     | Project name (required)                                      |
| `AZURE_PAT`         | Personal Access Token with *Build (read)* scope (required)   |
| `AZURE_PIPELINE_ID` | Pipeline definition ID, narrows searches                     |
| `POLL_INTERVAL`     | Seconds between polls (default: 30)                          |
| `LOG_TAIL`          | Lines shown per failing task (default: 80)                   |
| `NEW_BUILD_TIMEOUT` | Seconds to wait for a build of the local HEAD (default: 60)  |

Exit code: `0` succeeded or partially succeeded, `1` failed, `2` canceled, `3` other.
