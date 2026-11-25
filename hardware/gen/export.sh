#!/bin/sh
# Выходные файлы для заказа одной командой, без KiCad: BOM и карта выводов (outputs.py),
# гербера, сверловка, pos.csv, PDF платы и схемы, архив (export.py). Python - обычный,
# pcbnew и kicad-cli заменяет kroute (KROUTE_DIR, по умолчанию ../../autorouter).
cd "$(dirname "$0")/.."
KR="${KROUTE_DIR:-$(cd ../../autorouter 2>/dev/null && pwd)}"
[ -f "$KR/python/kroute_cli.py" ] || { echo "нет kroute: задайте KROUTE_DIR"; exit 1; }
export PYTHONPATH="$KR/python" PYTHONUTF8=1
PY="${PYTHON:-python}"
"$PY" gen/outputs.py drain_watcher.kicad_pcb
"$PY" gen/export.py .
