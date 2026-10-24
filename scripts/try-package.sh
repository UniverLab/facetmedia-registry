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
fi
export FACET_REGISTRY="${repo}"

section() {
  echo
  echo "===== ${1} ====="
}

section "facet run ${pkg}.${cap} ${piece}"
run=$(facet run "${pkg}.${cap}" "${piece}" --out "${work}/out" --json)
echo "${run}"

# The first asset of the record: out_dir + "/" + the asset's path.
asset=$(
  printf '%s' "${run}" |
    python3 -c 'import json, sys; data = json.load(sys.stdin); print(data["out_dir"] + "/" + data["assets"][0]["path"])'
)

section "facet preview ${asset}"
facet preview "${asset}" --json

section "facet doctor ${pkg}"
facet doctor "${pkg}" --json

section "facet skill ${pkg}"
facet skill "${pkg}"
