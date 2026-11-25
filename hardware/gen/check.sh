#!/bin/sh
# Сборка платы и все проверки одной командой (Git Bash / Linux), без KiCad:
# плату строит обычный Python с pcbnew-заглушкой из kroute, DRC, сверку схемы
# с платой и ERC делает kroute. KROUTE_DIR - репозиторий kroute (по умолчанию
# ../../autorouter рядом с проектом), KROUTE - готовый kroute.exe, если он не там.
cd "$(dirname "$0")/.."
KR="${KROUTE_DIR:-$(cd ../../autorouter 2>/dev/null && pwd)}"
[ -f "$KR/python/kroute_check.py" ] || { echo "нет kroute: задайте KROUTE_DIR"; exit 1; }
export PYTHONPATH="$KR/python" PYTHONUTF8=1
PY="${PYTHON:-python}"
NAME=drain_watcher
"$PY" gen/build.py .
"$PY" gen/route.py "$NAME.kicad_pcb"
"$PY" "$KR/python/kroute_check.py" "$NAME.kicad_pcb"
"$PY" gen/drc.py "$NAME.kicad_pcb"
"$PY" gen/conn.py "$NAME.kicad_pcb" | tail -3
"$PY" gen/crtyd.py "$NAME.kicad_pcb"
"$PY" gen/silkchk.py "$NAME.kicad_pcb"
