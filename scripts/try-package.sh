#!/usr/bin/env bash
# The manual heavy test of every package spec: one real `facet run` against
# this working copy, then the preview, the doctor report and the skill.
#
#   scripts/try-package.sh <package> <capability> <piece> [--keep-home]
#
# Uses facet from FACETMEDIA_REF (default feature/v0.1) through uvx, and this
# checkout as the registry (FACET_REGISTRY). With --keep-home the FACET_HOME
# is kept for inspection (default: your ~/.facet); otherwise everything runs
# in a temp home that is removed at the end. Run heavy packages alone.
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "usage: $0 <package> <capability> <piece> [--keep-home]" >&2
  exit 2
fi

pkg=$1
cap=$2
piece=$3
shift 3

keep_home=0
for arg in "$@"; do
  case "$arg" in
    --keep-home) keep_home=1 ;;
    *)
      echo "unknown argument: $arg" >&2
      echo "usage: $0 <package> <capability> <piece> [--keep-home]" >&2
      exit 2
      ;;
  esac
done

repo=$(cd "$(dirname "$0")/.." && pwd)
ref=${FACETMEDIA_REF:-feature/v0.1}

facet() {
  uvx --from "git+https://github.com/UniverLab/facetmedia@${ref}" facet "$@"
}

work=$(mktemp -d)
if [ "${keep_home}" = "0" ]; then
  trap 'rm -rf "${work}"' EXIT
  export FACET_HOME="${work}/home"
else
  export FACET_HOME="${FACET_HOME:-${HOME}/.facet}"
  echo "keeping ${work} (assets in ${work}/out)"
fi
export FACET_REGISTRY="${repo}"

section() {
  echo
  echo "===== ${1} ====="
}

# The record is printed even when the run fails: a verification failure (exit
# 3) still carries every record, and that is what the manual test is read for.
section "facet run ${pkg}.${cap} ${piece}"
run_status=0
run=$(facet run "${pkg}.${cap}" "${piece}" --out "${work}/out" --json) || run_status=$?
printf '%s\n' "${run}"

# The first asset of the record: out_dir + "/" + the asset's path. A run that
# failed before producing anything leaves none, and there is nothing to show.
asset=$(
  printf '%s' "${run}" | python3 -c '
import json, sys

data = json.load(sys.stdin)
assets = data.get("assets") or []
print(data["out_dir"] + "/" + assets[0]["path"] if assets else "")
'
) || asset=""
if [ -z "${asset}" ]; then
  echo "try-package: the run left no asset to preview" >&2
  if [ "${run_status}" -ne 0 ]; then
    exit "${run_status}"
  fi
  exit 1
fi

# The preview, the doctor and the skill all print: a failed verification or a
# failing doctor (a missing GPU, an unaccepted model) must not hide the rest, so
# every step runs and the script exits with the last non-zero status.
status=${run_status}
section "facet preview ${asset}"
facet preview "${asset}" --json || status=$?

section "facet doctor ${pkg}"
facet doctor "${pkg}" --json || status=$?

section "facet skill ${pkg}"
facet skill "${pkg}" || status=$?

if [ "${status}" -ne 0 ]; then
  echo "try-package: a step failed (exit ${status})" >&2
fi
exit "${status}"
