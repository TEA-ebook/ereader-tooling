#!/bin/bash
# Create and check out a git branch named after a Jira ticket:
#   <type>/LIS-<id>-<slugified-summary>
# The type comes from the ticket labels (feature, bugfix, hotfix, refacto, misc),
# then from the issue type. If neither matches, you pick it (fzf if available).
#
# Usage: create-branch.sh <ticket-id>
#   ticket-id: 1234, LIS-1234, or a full Jira browse URL
#
# Requires: curl, python3, git (fzf optional)
# Required env vars:
#   JIRA_USER   your Atlassian account email
#   JIRA_TOKEN  your Atlassian API token
#               (https://id.atlassian.com/manage-profile/security/api-tokens)

BASE_URL="https://tea-ebook.atlassian.net"
PROJECT_PREFIX="LIS"
TYPES="feature bugfix hotfix refacto misc"

extract_id() {
  local input="$1"
  if echo "$input" | grep -qiE 'atlassian\.net/browse/'"$PROJECT_PREFIX"'-[0-9]+'; then
    input=$(echo "$input" | grep -oiE "$PROJECT_PREFIX"'-[0-9]+')
  fi
  if echo "$input" | grep -qiE '^'"$PROJECT_PREFIX"'-[0-9]+$'; then
    echo "$input" | grep -oiE '[0-9]+$'
    return 0
  fi
  if echo "$input" | grep -qE '^[0-9]+$'; then
    echo "$input"
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

ID=$(extract_id "$1")
if [ -z "$ID" ]; then
  echo "Error: invalid ticket id: $1" >&2
  exit 1
fi

if [ -z "$JIRA_USER" ] || [ -z "$JIRA_TOKEN" ]; then
  echo "Error: JIRA_USER and JIRA_TOKEN must be set" >&2
  echo "Create a token at https://id.atlassian.com/manage-profile/security/api-tokens" >&2
  exit 1
fi

ISSUE_KEY="${PROJECT_PREFIX}-${ID}"
# Jira answers 404 for unauthenticated issue requests, so check the credentials first
AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -u "${JIRA_USER}:${JIRA_TOKEN}" "${BASE_URL}/rest/api/3/myself")
if [ "$AUTH_STATUS" != "200" ]; then
  echo "Error: Jira authentication failed (HTTP ${AUTH_STATUS}); check JIRA_USER and JIRA_TOKEN" >&2
  echo "Create a new token at https://id.atlassian.com/manage-profile/security/api-tokens" >&2
  exit 1
fi

RESPONSE=$(curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
  "${BASE_URL}/rest/api/3/issue/${ISSUE_KEY}?fields=summary,labels,issuetype")

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

SLUG=$(echo "$TITLE" | sed 's/([^)]*)//g' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/-\+/-/g' | sed 's/^-\|-$//g')
BRANCH="${TYPE}/${ISSUE_KEY}-${SLUG}"
git checkout -b "$BRANCH"
