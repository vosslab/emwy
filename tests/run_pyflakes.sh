#!/usr/bin/env bash
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

# Run pyflakes on all Python files and capture output
PYFLAKES_OUT="${REPO_ROOT}/pyflakes.txt"
find "${REPO_ROOT}" \
	-type d \( -name .git -o -name .venv \) -prune -o \
	-type f -name "*.py" -print0 \
	| sort -z \
	| xargs -0 pyflakes > "${PYFLAKES_OUT}" 2>&1 || true

RESULT=$(wc -l < "${PYFLAKES_OUT}")

N=5

# Success if no errors were found
if [ "${RESULT}" -eq 0 ]; then
    echo "No errors found!!!"
    exit 0
fi

shorten_paths() {
	sed -E 's|.*/([^/:]+:)|\1|'
}

echo ""
echo "First ${N} errors"
head -n "${N}" "${PYFLAKES_OUT}" | shorten_paths
echo "-------------------------"
echo ""

echo "Random ${N} errors"
sort -R "${PYFLAKES_OUT}" | head -n "${N}" | shorten_paths || true
echo "-------------------------"
echo ""

echo "Last ${N} errors"
tail -n "${N}" "${PYFLAKES_OUT}" | shorten_paths
echo "-------------------------"
echo ""

echo "Found ${RESULT} pyflakes errors written to REPO_ROOT/pyflakes.txt"

# Fail if any errors were found
exit 1
