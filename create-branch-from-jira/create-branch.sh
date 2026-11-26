#!/bin/bash
# Create and check out a git branch named after a Jira ticket:
#   <type>/<PROJECT>-<id>-<slugified-summary>
# The type comes from the ticket labels (feature, bugfix, hotfix, refacto, misc),
# then from the issue type. If neither matches, you pick it (fzf if available).
# Then it offers to assign the ticket to you and move it to "In progress".
#
# If wtp (https://github.com/satococoa/wtp) is installed, the branch is created
# in a new worktree instead of being checked out in place. You pick the worktree
# folder name (default: the issue key), and a new shell opens in that folder.
#
# Usage: create-branch.sh <ticket-id>
#   ticket-id: 1234 (LIS project), any issue key such as BNB-1234 or RDR-1234,
#              or a full Jira browse URL
#
# Requires: curl, python3, git (fzf and wtp optional)
# Required env vars:
#   JIRA_USER   your Atlassian account email
#   JIRA_TOKEN  your Atlassian API token
#               (https://id.atlassian.com/manage-profile/security/api-tokens)

BASE_URL="https://tea-ebook.atlassian.net"
DEFAULT_PROJECT="LIS"
TYPES="feature bugfix hotfix refacto misc"

# Print the issue key (PROJECT-1234) for a ticket id, a key or a browse URL.
# A bare number is a ticket of the default project.
extract_key() {
  local input="$1" key
  input=$(echo "$input" | sed -E 's|^.*atlassian\.net/browse/||; s|[?#].*$||')
  key=$(echo "$input" | grep -xiE '[a-z][a-z0-9_]*-[0-9]+')
  if [ -n "$key" ]; then
    echo "$key" | tr '[:lower:]' '[:upper:]'
    return 0
  fi
  if echo "$input" | grep -qE '^[0-9]+$'; then
    echo "${DEFAULT_PROJECT}-${input}"
    return 0
  fi
  return 1
}

pick_type() {
  if command -v fzf &>/dev/null; then
    echo "$TYPES" | tr ' ' '\n' | fzf --prompt="Branch type: " --height=7
  else
    echo "Select branch type:" >&2
    select t in $TYPES; do
      [ -n "$t" ] && echo "$t" && return
    done
  fi
}

if [ -z "$1" ]; then
  echo "Usage: $(basename "$0") <ticket-id>" >&2
  exit 1
fi

ISSUE_KEY=$(extract_key "$1")
if [ -z "$ISSUE_KEY" ]; then
  echo "Error: invalid ticket id: $1" >&2
  exit 1
fi

if [ -z "$JIRA_USER" ] || [ -z "$JIRA_TOKEN" ]; then
  echo "Error: JIRA_USER and JIRA_TOKEN must be set" >&2
  echo "Create a token at https://id.atlassian.com/manage-profile/security/api-tokens" >&2
  exit 1
fi

# Jira answers 404 for unauthenticated issue requests, so check the credentials first
MYSELF=$(curl -s -w "\n%{http_code}" -u "${JIRA_USER}:${JIRA_TOKEN}" "${BASE_URL}/rest/api/3/myself")
AUTH_STATUS=$(echo "$MYSELF" | tail -n1)
MY_ACCOUNT_ID=$(echo "$MYSELF" | sed '$d' | python3 -c "import sys,json; print(json.load(sys.stdin)['accountId'])" 2>/dev/null)
if [ "$AUTH_STATUS" != "200" ]; then
  echo "Error: Jira authentication failed (HTTP ${AUTH_STATUS}); check JIRA_USER and JIRA_TOKEN" >&2
  echo "Create a new token at https://id.atlassian.com/manage-profile/security/api-tokens" >&2
  exit 1
fi

RESPONSE=$(curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
  "${BASE_URL}/rest/api/3/issue/${ISSUE_KEY}?fields=summary,labels,issuetype,assignee,status")

TITLE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['fields']['summary'])" 2>/dev/null)

if [ -z "$TITLE" ]; then
  echo "Error: could not retrieve title for ${ISSUE_KEY}" >&2
  echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('errorMessages',d))" 2>/dev/null >&2
  exit 1
fi

# 1. Labels take priority
TYPE=""
LABELS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(d['fields'].get('labels', [])))" 2>/dev/null | tr '[:upper:]' '[:lower:]')
for t in $TYPES; do
  if echo "$LABELS" | grep -qw "$t"; then
    TYPE="$t"
    break
  fi
done

# 2. Fall back to issue type mapping
if [ -z "$TYPE" ]; then
  ISSUETYPE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['fields']['issuetype']['name'].lower())" 2>/dev/null)
  case "$ISSUETYPE" in
    bug)                              TYPE="bugfix" ;;
    story|"new feature"|improvement|epic) TYPE="feature" ;;
    hotfix)                           TYPE="hotfix" ;;
    refactor|refactoring)             TYPE="refacto" ;;
    task|sub-task*|"sub-task-dev")    TYPE="misc" ;;
  esac
fi

if [ -z "$TYPE" ]; then
  TYPE=$(pick_type)
  [ -z "$TYPE" ] && exit 1
fi

# Slugify: drop text in parentheses, transliterate accents (é -> e),
# keep only [a-z0-9], collapse dashes, cap the length
SLUG=$(TITLE="$TITLE" python3 -c '
import os, re, unicodedata
s = re.sub(r"\([^)]*\)", "", os.environ["TITLE"])
s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
print(s[:60].rstrip("-"))
')
BRANCH="${TYPE}/${ISSUE_KEY}"
[ -n "$SLUG" ] && BRANCH="${BRANCH}-${SLUG}"

if ! git check-ref-format --branch "$BRANCH" &>/dev/null; then
  echo "Error: invalid branch name: $BRANCH" >&2
  exit 1
fi

WORKTREE=""
if command -v wtp &>/dev/null; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "Error: branch $BRANCH already exists" >&2
    exit 1
  fi
  read -r -e -p "Worktree folder: " -i "$ISSUE_KEY" FOLDER
  [ -z "$FOLDER" ] && exit 1
  # wtp names the folder after the branch, so create the worktree on a branch
  # named after the folder, then rename the branch
  wtp add -b "$FOLDER" || exit 1
  WORKTREE=$(wtp cd "$FOLDER") || exit 1
  git -C "$WORKTREE" branch -m "$BRANCH" || exit 1
else
  git checkout -b "$BRANCH" || exit 1
fi

# Exit, or with wtp open a shell in the new worktree.
# A script cannot change the directory of its caller, so open a new shell there.
finish() {
  if [ -n "$WORKTREE" ]; then
    echo "Opening a shell in $WORKTREE (exit to go back)"
    cd "$WORKTREE" && exec "${SHELL:-bash}"
  fi
  exit 0
}

# Offer to take the ticket: assign it to me and move it to "In progress"
ASSIGNEE_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; a=json.load(sys.stdin)['fields'].get('assignee'); print(a['accountId'] if a else '')" 2>/dev/null)
STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['fields']['status']['name'])" 2>/dev/null)
STATUS_LC=$(echo "$STATUS" | tr '[:upper:]' '[:lower:]')
IN_PROGRESS_NAMES="in progress|en cours"

if [ "$ASSIGNEE_ID" = "$MY_ACCOUNT_ID" ] && echo "$STATUS_LC" | grep -qxE "$IN_PROGRESS_NAMES"; then
  finish
fi
[ -r /dev/tty ] || finish

read -r -p "Assign ${ISSUE_KEY} to you and mark it as in progress (now: ${STATUS})? [Y/n] " ANSWER </dev/tty
case "$ANSWER" in
  ""|[yY]*) ;;
  *) finish ;;
esac

if [ "$ASSIGNEE_ID" != "$MY_ACCOUNT_ID" ]; then
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "${JIRA_USER}:${JIRA_TOKEN}" -X PUT \
    -H "Content-Type: application/json" -d "{\"accountId\":\"${MY_ACCOUNT_ID}\"}" \
    "${BASE_URL}/rest/api/3/issue/${ISSUE_KEY}/assignee")
  if [ "$CODE" = "204" ]; then
    echo "Assigned ${ISSUE_KEY} to you"
  else
    echo "Error: could not assign ${ISSUE_KEY} (HTTP ${CODE})" >&2
  fi
fi

if ! echo "$STATUS_LC" | grep -qxE "$IN_PROGRESS_NAMES"; then
  TRANSITION_ID=$(curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" "${BASE_URL}/rest/api/3/issue/${ISSUE_KEY}/transitions" \
    | python3 -c "
import sys, json, re
for t in json.load(sys.stdin).get('transitions', []):
    if re.fullmatch(r'$IN_PROGRESS_NAMES', t['to']['name'].lower()):
        print(t['id'])
        break
" 2>/dev/null)
  if [ -z "$TRANSITION_ID" ]; then
    echo "Error: no transition to \"In progress\" from \"${STATUS}\" for ${ISSUE_KEY}" >&2
    finish
  fi
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "${JIRA_USER}:${JIRA_TOKEN}" -X POST \
    -H "Content-Type: application/json" -d "{\"transition\":{\"id\":\"${TRANSITION_ID}\"}}" \
    "${BASE_URL}/rest/api/3/issue/${ISSUE_KEY}/transitions")
  if [ "$CODE" = "204" ]; then
    echo "Moved ${ISSUE_KEY} to in progress"
  else
    echo "Error: could not move ${ISSUE_KEY} to in progress (HTTP ${CODE})" >&2
  fi
fi
finish
