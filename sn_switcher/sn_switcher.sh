#!/usr/bin/env bash
# Usage: sn_switcher.sh [-c config.csv] [name|number]
# Config: CSV with the header "name,serial", then one "<name>,<serial>" per row.
# Without an argument, opens a menu: arrows (or j/k) to move, Enter or Space to apply, q/Esc to quit.
set -euo pipefail

config="${SN_CONFIG:-$HOME/qboo/serials.conf}"
sn_file="$HOME/qboo/private/prod/sn"

if [[ "${1:-}" == "-c" ]]; then
    config="$2"
    shift 2
fi

names=()
serials=()
line_number=0
while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    line="${line%$'\r'}"
    if [[ $line_number -eq 1 ]]; then
        if [[ "$line" != "name,serial" ]]; then
            echo "$config:1: header must be 'name,serial'" >&2
            exit 1
        fi
        continue
    fi
    [[ -z "$line" ]] && continue
    IFS=, read -r name serial extra <<< "$line"
    if [[ -z "$name" || -z "$serial" || -n "${extra:-}" ]]; then
        echo "$config:$line_number: expected exactly 'name,serial'" >&2
        exit 1
    fi
    names+=("$name")
    serials+=("$serial")
done < "$config"

if [[ ${#names[@]} -eq 0 ]]; then
    echo "$config: no entries" >&2
    exit 1
fi

current="$(cat "$sn_file" 2>/dev/null || true)"

apply() {
    printf '%s\n' "${serials[$1]}" > "$sn_file"
    echo "sn -> ${names[$1]} (${serials[$1]})"
}

if [[ $# -gt 0 ]]; then
    for i in "${!names[@]}"; do
        if [[ "${names[$i]}" == "$1" || "$((i + 1))" == "$1" ]]; then
            apply "$i"
            exit 0
        fi
    done
    echo "Unknown entry: $1" >&2
    exit 1
fi

count=${#names[@]}
selected=0
for i in "${!serials[@]}"; do
    [[ "${serials[$i]}" == "$current" ]] && selected=$i
done

tput civis 2>/dev/null || true
trap 'tput cnorm 2>/dev/null || true' EXIT

while true; do
    for i in "${!names[@]}"; do
        marker=" "
        [[ "${serials[$i]}" == "$current" ]] && marker="*"
        [[ $i -eq $selected ]] && printf '\e[7m'
        printf '%s %s%*s %s\e[0m\e[K\n' "$marker" "${names[$i]}" $((24 - ${#names[$i]})) '' "${serials[$i]}"
    done

    IFS= read -rsn1 key
    if [[ "$key" == $'\e' ]]; then
        read -rsn2 -t 0.01 key || key=$'\e'
    fi
    case "$key" in
        '[A' | k) selected=$(((selected - 1 + count) % count)) ;;
        '[B' | j) selected=$(((selected + 1) % count)) ;;
        '' | ' ')
            apply "$selected"
            exit 0
            ;;
        q | $'\e') exit 0 ;;
    esac
    printf '\e[%dA' "$count"
done
