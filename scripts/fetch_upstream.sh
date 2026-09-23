#!/usr/bin/env bash
# Fetch the openai_conversation integration from home-assistant/core.
#
# Usage:
#   fetch_upstream.sh latest-tag          Print the newest stable core tag.
#   fetch_upstream.sh fetch <tag> <dest>  Sparse-checkout the integration
#                                         (plus homeassistant/strings.json for
#                                         translation references) into <dest>.
set -euo pipefail

CORE_REPO="https://github.com/home-assistant/core.git"
INTEGRATION_PATH="homeassistant/components/openai_conversation"
STABLE_TAG_RE='^[0-9]{4}\.[0-9]{1,2}\.[0-9]+$'

latest_tag() {
  git ls-remote --tags --refs "$CORE_REPO" \
    | awk -F/ '{print $3}' \
    | grep -E "$STABLE_TAG_RE" \
    | sort -V \
    | tail -n 1
}

fetch() {
  local tag="$1" dest="$2"
  if ! [[ "$tag" =~ $STABLE_TAG_RE ]]; then
    echo "error: '$tag' is not a stable core tag" >&2
    exit 1
  fi
  rm -rf "$dest"
  git clone --quiet --depth 1 --branch "$tag" --filter=blob:none --no-checkout \
    "$CORE_REPO" "$dest"
  git -C "$dest" sparse-checkout set --no-cone \
    "/$INTEGRATION_PATH/" "/homeassistant/strings.json"
  git -C "$dest" -c advice.detachedHead=false checkout --quiet "$tag"
  if [[ ! -d "$dest/$INTEGRATION_PATH" ]]; then
    echo "error: $INTEGRATION_PATH not found in core $tag" >&2
    exit 1
  fi
}

case "${1:-}" in
  latest-tag)
    tag="$(latest_tag)"
    if [[ -z "$tag" ]]; then
      echo "error: no stable tag found" >&2
      exit 1
    fi
    echo "$tag"
    ;;
  fetch)
    [[ $# -eq 3 ]] || { echo "usage: $0 fetch <tag> <dest>" >&2; exit 2; }
    fetch "$2" "$3"
    ;;
  *)
    echo "usage: $0 latest-tag | fetch <tag> <dest>" >&2
    exit 2
    ;;
esac
