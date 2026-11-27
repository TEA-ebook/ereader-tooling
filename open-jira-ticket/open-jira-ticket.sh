#!/bin/bash
# Open a Jira ticket in the browser, from the selected text or from a prompt.
# Bind this script to a keyboard shortcut in your desktop environment.
#
# Accepted input:
#   1234                     ticket of the default project (LIS-1234)
#   BNB-1234, rdr-12         ticket of any project
#   a Jira browse URL
#
# The selected text (X11 primary selection, needs xclip) is used first.
# If it is not a ticket, a dialog asks for one (zenity, kdialog or xterm).

BASE_URL="https://tea-ebook.atlassian.net/browse"
DEFAULT_PROJECT="LIS"
HINT="1234, ${DEFAULT_PROJECT}-1234 or BNB-1234"

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

error() {
  if command -v zenity &>/dev/null; then
    zenity --error --text="$1" --width=300 2>/dev/null
  elif command -v kdialog &>/dev/null; then
    kdialog --error "$1"
  else
    echo "Error: $1" >&2
  fi
}

SELECTED=""
if command -v xclip &>/dev/null; then
  SELECTED=$(xclip -o -selection primary 2>/dev/null | tr -d '[:space:]')
fi

KEY=$(extract_key "$SELECTED")

if [ -z "$KEY" ]; then
  if command -v zenity &>/dev/null; then
    INPUT=$(zenity --entry --title="Open Jira Ticket" \
      --text="Enter the ticket (e.g. ${HINT}):" --width=350 2>/dev/null) || exit 0
  elif command -v kdialog &>/dev/null; then
    INPUT=$(kdialog --title "Open Jira Ticket" --inputbox "Enter the ticket (e.g. ${HINT}):" 2>/dev/null) || exit 0
  else
    INPUT=$(xterm -T "Open Jira Ticket" -e "bash -c 'read -p \"Ticket (e.g. ${HINT}): \" v && echo \$v'" 2>/dev/null)
  fi

  INPUT=$(echo "$INPUT" | tr -d '[:space:]')
  [ -z "$INPUT" ] && exit 0
  KEY=$(extract_key "$INPUT")
  if [ -z "$KEY" ]; then
    error "Invalid input: \"$INPUT\"
Expected a ticket like ${HINT}."
    exit 1
  fi
fi

URL="${BASE_URL}/${KEY}"
for browser in xdg-open brave-browser firefox google-chrome; do
  if command -v "$browser" &>/dev/null; then
    "$browser" "$URL" &>/dev/null &
    exit 0
  fi
done
error "No browser found to open: $URL"
exit 1
