#!/usr/bin/env bash
set -uo pipefail

usage() {
  echo "uso: $0 <raiz-nwo-maps> [--deep-spr] [--skip-tests]" >&2
}

if (($# < 1 || $# > 3)); then
  usage
  exit 2
fi

root=$1
shift
deep_spr=0
skip_tests=0
for arg in "$@"; do
  case "$arg" in
    --deep-spr) deep_spr=1 ;;
    --skip-tests) skip_tests=1 ;;
    *) usage; exit 2 ;;
  esac
done

if [[ ! -d "$root" ]]; then
  echo "erro: diretório não encontrado: $root" >&2
  exit 2
fi
root=$(cd "$root" && pwd -P)
if [[ ! -d "$root/nwoassets" ]] || ! git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "erro: raiz não contém nwoassets/ e checkout Git válidos: $root" >&2
  exit 2
fi

scratch_base=${PAPERCLIP_RUN_SCRATCH_DIR:-${PAPERCLIP_SCRATCH_DIR:-${TMPDIR:-/tmp}}}
mkdir -p "$scratch_base"
run_dir=$(mktemp -d "$scratch_base/validate-nwo-assets.XXXXXX")
report="$run_dir/validation.json"
before="$run_dir/git-before.bin"
after="$run_dir/git-after.bin"
test_log="$run_dir/tests.log"
cli_log="$run_dir/validate.log"

git -C "$root" status --porcelain=v1 -z --untracked-files=all >"$before"

test_rc=0
if ((skip_tests == 0)); then
  (
    cd "$root"
    PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$run_dir/pycache" \
      python3 -B -m unittest discover -s tests -v
  ) >"$test_log" 2>&1 || test_rc=$?
fi

cli_rc=0
if ((test_rc == 0)); then
  cli_args=(validate "$root" -o "$report")
  if ((deep_spr == 1)); then
    cli_args+=(--deep-spr)
  fi
  (
    cd "$root"
    PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$run_dir/pycache" \
      python3 -B -m nwoassets "${cli_args[@]}"
  ) >"$cli_log" 2>&1 || cli_rc=$?
fi

git -C "$root" status --porcelain=v1 -z --untracked-files=all >"$after"
if ! cmp -s "$before" "$after"; then
  echo "erro: status Git mudou durante a validação" >&2
  echo "evidência: $run_dir" >&2
  exit 3
fi

if ((test_rc != 0)); then
  cat "$test_log" >&2
  echo "erro: testes retornaram código $test_rc" >&2
  echo "evidência: $run_dir" >&2
  exit "$test_rc"
fi
if ((cli_rc != 0)); then
  cat "$cli_log" >&2
  echo "erro: validação retornou código $cli_rc" >&2
  echo "evidência: $run_dir" >&2
  exit "$cli_rc"
fi

if [[ ! -s "$report" ]]; then
  echo "erro: validação não produziu relatório JSON" >&2
  echo "evidência: $run_dir" >&2
  exit 2
fi

python3 - "$report" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)
print(f"passed: {str(bool(report.get('passed'))).lower()}")
print(f"errors: {len(report.get('errors', []))}")
print(f"warnings: {len(report.get('warnings', []))}")
PY
echo "tests: $([[ $skip_tests -eq 1 ]] && echo skipped || echo passed)"
echo "git_status_unchanged: true"
echo "report: $report"
echo "evidência: $run_dir"
