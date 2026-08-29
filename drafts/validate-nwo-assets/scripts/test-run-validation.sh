#!/usr/bin/env bash
set -uo pipefail

skill_dir=$(cd "$(dirname "$0")/.." && pwd -P)
runner="$skill_dir/scripts/run-validation.sh"
repo=${1:-/workspaces/nwo-maps}
scratch_base=${PAPERCLIP_RUN_SCRATCH_DIR:-${PAPERCLIP_SCRATCH_DIR:-${TMPDIR:-/tmp}}}
suite_dir=$(mktemp -d "$scratch_base/test-validate-nwo-assets.XXXXXX")
failures=0

run_case() {
  local name=$1 expected=$2
  shift 2
  local rc=0
  "$@" >"$suite_dir/$name.out" 2>"$suite_dir/$name.err" || rc=$?
  if [[ $rc -ne $expected ]]; then
    echo "FAIL $name: esperado $expected, obtido $rc" >&2
    failures=$((failures + 1))
  else
    echo "PASS $name ($rc)"
  fi
}

if [[ ! -d "$repo/.git" ]]; then
  echo "erro: informe a raiz do checkout nwo-maps" >&2
  exit 2
fi
before_hash=$(git -C "$repo" status --porcelain=v1 -z --untracked-files=all | sha256sum)

run_case missing-root 2 "$runner" "$suite_dir/ausente"

fixture="$suite_dir/mixed-signature"
mkdir -p "$fixture"
git -C "$repo" ls-files -z | while IFS= read -r -d '' path; do
  case "$path" in
    .gitignore|*/.gitignore|.gitattributes|*/.gitattributes) continue ;;
  esac
  mkdir -p "$fixture/$(dirname "$path")"
  ln -s "$repo/$path" "$fixture/$path"
done
rm "$fixture/860/Tibia.spr"
python3 - "$fixture/860/Tibia.spr" <<'PY'
import struct
import sys
with open(sys.argv[1], "wb") as stream:
    stream.write(struct.pack("<I", 0x53835077))
PY
git -C "$fixture" init -q
git -C "$fixture" add .
run_case mixed-signature 2 "$runner" "$fixture" --skip-tests

fake_bin="$suite_dir/fake-bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/python3" <<'SH'
#!/usr/bin/env bash
exit 7
SH
chmod +x "$fake_bin/python3"
run_case nonzero-command 7 env PATH="$fake_bin:$PATH" "$runner" "$repo"

run_case baseline-success 0 "$runner" "$repo"

after_hash=$(git -C "$repo" status --porcelain=v1 -z --untracked-files=all | sha256sum)
if [[ "$before_hash" != "$after_hash" ]]; then
  echo "FAIL git-status-stable" >&2
  failures=$((failures + 1))
else
  echo "PASS git-status-stable"
fi

echo "logs: $suite_dir"
exit "$failures"
