#!/usr/bin/env python3
"""Выходные файлы платы: гербера, сверловка, pos.csv, PDF и архив для завода.

    python gen/export.py hardware

Всё делает kicad-cli, здесь только один и тот же набор ключей для всех плат,
чтобы у двух плат сходились имена файлов и настройки.
"""
import glob
import os
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

LAYERS = ("F.Cu,B.Cu,F.Paste,B.Paste,"
          "F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts")      # плата 2-слойная


def cli():
    """kicad-cli рядом с тем pcbnew, которым собрана плата."""
    exe = "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
    near = os.path.join(os.path.dirname(os.path.dirname(kicadenv.share_dir())), "bin", exe)
    return near if os.path.exists(near) else exe


def run(*args):
    r = subprocess.run([cli()] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("kicad-cli %s:\n%s" % (args[:3], r.stderr.strip()[-800:]))
    return r.stdout.strip()


# JLCPCB разбирает CPL по именам колонок и родные заголовки KiCad не понимает -
# файл отвергается целиком ("Failed processing the CPL file"). Переименовываем.
CPLHDR = {"Ref": "Designator", "PosX": "Mid X", "PosY": "Mid Y",
          "Rot": "Rotation", "Side": "Layer"}


# Поправка поворота для CPL. Библиотека JLCPCB собрана из футпринтов EasyEDA, и
# у них другое соглашение о том, в каком углу корпуса нулевой вывод: для QFP это
# регулярно даёт расхождение на 90 градусов с официальными футпринтами KiCad.
# Правка только в CPL - на самой плате и в схеме ничего не меняется.
# Подобрано по gen/jlc_check.py (сверка с посадочными местами JLCPCB по номерам LCSC):
# у SOT-23-5/6 и VSSOP у EasyEDA выводы вдоль длинной стороны горизонтально, у KiCad -
# вертикально.
ROT_FIX = {"U2": 270, "U3": 270, "U4": 270}

# Поправка положения для CPL, мм на плате (x вправо, y вниз): у EasyEDA начало координат
# детали не там, где у KiCad. Модуль ESP32-S3 - у них центр по падам, у KiCad - по
# корпусу с антенной; USB-C - у них по-своему по высоте.
POS_FIX = {"U1": (3.62, 0.0), "J1": (0.0, -1.57)}


def jlc_cpl(path):
    import csv
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return
    hdr = rows[0]
    rows[0] = [CPLHDR.get(c, c) for c in hdr]
    ir = rows[0].index("Rotation") if "Rotation" in rows[0] else None
    fixed = []
    ix, iy = rows[0].index("Mid X"), rows[0].index("Mid Y")
    for r in rows[1:]:
        if ir is not None and r[0] in ROT_FIX:
            r[ir] = "%.6f" % ((float(r[ir]) + ROT_FIX[r[0]]) % 360.0)
            fixed.append(r[0])
        if r[0] in POS_FIX:
            dx, dy = POS_FIX[r[0]]
            r[ix] = "%.6f" % (float(r[ix]) + dx)
            r[iy] = "%.6f" % (float(r[iy]) - dy)       # в CPL y вверх
            fixed.append(r[0])
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    if fixed:
        print("поворот в CPL поправлен: %s" % ", ".join(fixed))


def main(out):
    out = os.path.abspath(out)              # kicad-cli путается в относительных путях
    name = "drain_watcher"
    pcb = os.path.join(out, name + ".kicad_pcb")
    sch = os.path.join(out, name + ".kicad_sch")
    gerb = os.path.join(out, "gerbers")
    if not os.path.exists(pcb):
        raise SystemExit("нет платы: %s" % pcb)

    shutil.rmtree(gerb, ignore_errors=True)
    os.makedirs(gerb, exist_ok=True)
    run("pcb", "export", "gerbers", "--layers", LAYERS, "-o", gerb, pcb)
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
        "--excellon-units", "mm", "-o", gerb, pcb)
    print("гербера:", len(os.listdir(gerb)), "файлов")

    zpath = os.path.join(out, name + "_gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gerb)):
            z.write(os.path.join(gerb, f), f)
    print("архив:", os.path.basename(zpath))

    pos = os.path.join(out, "pos.csv")
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
        "-o", pos, pcb)
    jlc_cpl(pos)
    run("pcb", "export", "pdf", "--layers", "F.Cu,F.Silkscreen,Edge.Cuts",
        "-o", os.path.join(out, "top.pdf"), pcb)
    run("pcb", "export", "pdf", "--layers", "B.Cu,B.Silkscreen,Edge.Cuts",
        "-o", os.path.join(out, "bot.pdf"), pcb)
    if os.path.exists(sch):
        run("sch", "export", "pdf", "-o", os.path.join(out, "sch.pdf"), sch)
    print("pos.csv / top.pdf / bot.pdf / sch.pdf ->", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
