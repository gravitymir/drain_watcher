# -*- coding: utf-8 -*-
"""Проверка CPL против посадочных мест JLCPCB/EasyEDA: куда сядут их пады при нашем
Mid X/Y/Rotation - и насколько это далеко от наших падов. Ловит и сдвиг, и поворот, и полярность.
python gen/jlc_check.py <board.kicad_pcb> <pos.csv> <BOM.csv> [REF,REF - подробно по падам]

Оборот (Layer=bottom): JLCPCB зеркалит свою деталь. Схема зеркалирования BOTTOM
откалибрована по работающей плате H723 (AP2112K на обороте, CPL из коммита 53631e5)."""
import sys, os, csv, json, math, re, subprocess
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv; kicadenv.quiet()
import pcbnew
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_easyeda_cache")   # кэш посадочных мест JLCPCB
os.makedirs(CACHE, exist_ok=True)
U = 0.254
# варианты для оборота: (зеркалить x, знак поворота)
VARIANTS = {"mx+": (True, 1), "mx-": (True, -1), "my+": (False, 1), "my-": (False, -1)}
BOTTOM = os.environ.get("JLC_BOTTOM", "mx-")


def ee_pads(code):
    fn = os.path.join(CACHE, code + ".json")
    if not os.path.exists(fn):
        url = "https://easyeda.com/api/products/%s/components?version=6.4.19.5" % code
        # urllib сервер EasyEDA режет (403), curl пропускает
        subprocess.run(["curl", "-s", "-f", "-o", fn, url], check=True, timeout=60)
    d = json.load(open(fn, encoding="utf-8-sig"))
    ds = d["result"]["packageDetail"]["dataStr"]
    hx, hy = float(ds["head"]["x"]), float(ds["head"]["y"])
    out = []
    for s in ds["shape"]:
        if s.startswith("PAD~"):
            f = s.split("~")
            out.append((f[8], (float(f[2]) - hx) * U, -(float(f[3]) - hy) * U))   # y вверх
    return d["result"]["packageDetail"].get("title", ""), out


def place(ee, mx, my, deg, bottom, variant):
    """Их пады в координатах платы (вид сверху, y вверх)."""
    out = []
    mirx, sgn = VARIANTS[variant] if bottom else (False, 1)
    a = math.radians(deg) * sgn
    for num, ex, ey in ee:
        if bottom:
            ex, ey = (-ex, ey) if mirx else (ex, -ey)
        out.append((num, mx + ex * math.cos(a) - ey * math.sin(a), my + ex * math.sin(a) + ey * math.cos(a)))
    return out


def score(pl, kp):
    res = []
    for num, bx, by in pl:
        names = set(re.findall(r"[AB]\d+", num)) or {num}
        cand = [k for k in kp if k[0] in names] or kp   # пады корпуса без общего номера - ближайший
        d, k = min((math.hypot(bx - kx, by - ky), (kn, kx, ky)) for kn, kx, ky in cand)
        res.append((d, num, k[0], bx - k[1], by - k[2]))
    near = max(min(math.hypot(bx - kx, by - ky) for kn, kx, ky in kp) for num, bx, by in pl)
    return res, near


pcb, pos, bom = sys.argv[1:4]
detail = sys.argv[4].split(",") if len(sys.argv) > 4 else []
b = pcbnew.LoadBoard(pcb)
T = pcbnew.ToMM
kpads = {}
for fp in b.GetFootprints():
    kpads[fp.GetReference()] = [(p.GetNumber(), T(p.GetPosition().x), -T(p.GetPosition().y)) for p in fp.Pads()]
code_of = {}
for r in csv.DictReader(open(bom, encoding="utf-8-sig")):
    if r["LCSC Part #"]:
        for ref in r["Designator"].split(","):
            code_of[ref.strip()] = r["LCSC Part #"]

for r in csv.DictReader(open(pos, encoding="utf-8-sig")):
    ref = r["Designator"]
    if ref not in code_of:
        continue
    mx, my, deg = float(r["Mid X"]), float(r["Mid Y"]), float(r["Rotation"])
    bottom = r.get("Layer", "top").lower().startswith("b")
    title, ee = ee_pads(code_of[ref])
    kp = kpads[ref]
    pl = place(ee, mx, my, deg, bottom, BOTTOM)
    res, near = score(pl, kp)
    mean_dx = sum(z[3] for z in res) / len(res)
    mean_dy = sum(z[4] for z in res) / len(res)
    worst = max(res)
    # "~" - пады на местах, но нумерация у JLCPCB своя (кнопки) или пад нарезан иначе
    # (кольцо микрофона, сетка EP модуля): смотреть подробно, но обычно это норма
    flag = "OK " if worst[0] < 0.25 else ("~  " if near < 0.8 else "!!!")
    side = "низ" if bottom else "верх"
    print("%s %-4s %-4s %-9s пад макс %.2f мм (их %s -> наш %s), средний сдвиг (%+.2f, %+.2f) | %s" % (
        flag, ref, side, code_of[ref], worst[0], worst[1], worst[2], mean_dx, mean_dy, title))
    if bottom and ("calib" in detail):
        for v in VARIANTS:
            rr, nn = score(place(ee, mx, my, deg, True, v), kp)
            print("      вариант оборота %s: пад макс %.2f, геометрия %.2f" % (v, max(rr)[0], nn))
    if flag == "!!!" and (not detail or ref in detail):
        for num, bx, by in pl:
            d, kn = min((math.hypot(bx - kx, by - ky), kn) for kn, kx, ky in kp)
            print("      их пад %-6s -> ближайший наш %-4s в %.2f мм   (их центр %.2f, %.2f)" % (num, kn, d, bx, -by))
