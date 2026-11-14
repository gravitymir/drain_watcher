#!/bin/sh
# Сборка платы и все проверки одной командой (Git Bash / Linux).
cd "$(dirname "$0")/.."
PY="${KICAD_PY:-/c/Program Files/KiCad/10.0/bin/python.exe}"
CLI="${KICAD_CLI:-/c/Program Files/KiCad/10.0/bin/kicad-cli.exe}"
F='assert|image handler'
"$PY" gen/build.py . 2>&1 | grep -v -i -E "$F"
"$PY" gen/route.py drain_watcher.kicad_pcb 2>&1 | grep -v -i -E "$F|memory leak"
"$CLI" pcb drc --schematic-parity --severity-all -o drc.rpt drain_watcher.kicad_pcb >/dev/null 2>&1
grep -E "^\*\* Found" drc.rpt
grep -E "^\[" drc.rpt | sort | uniq -c
"$CLI" sch erc --severity-error -o erc.rpt drain_watcher.kicad_sch >/dev/null 2>&1
grep -E "^\*\* ERC|Found" erc.rpt | head -3
"$PY" gen/drc.py drain_watcher.kicad_pcb 2>&1 | grep -v -i -E "$F"
"$PY" gen/conn.py drain_watcher.kicad_pcb 2>&1 | grep -v -i -E "$F" | tail -3
"$PY" gen/crtyd.py drain_watcher.kicad_pcb 2>&1 | grep -v -i -E "$F"
"$PY" gen/silkchk.py drain_watcher.kicad_pcb 2>&1 | grep -v -i -E "$F"
