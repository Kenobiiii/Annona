#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Audit the locked production dependencies with pip-audit.
# Accepted exceptions live, with their reasons, in security/pip-audit-ignore.txt.
set -euo pipefail
cd "$(dirname "$0")/.."
requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT
uv export --locked --no-dev --no-emit-workspace --format requirements-txt > "$requirements"
ignores=()
while read -r id _; do
  [[ -z "$id" || "$id" == \#* ]] || ignores+=(--ignore-vuln "$id")
done < security/pip-audit-ignore.txt
uvx pip-audit --requirement "$requirements" --no-deps --disable-pip "${ignores[@]}"
