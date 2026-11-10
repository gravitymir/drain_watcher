#!/usr/bin/env python3
"""Генератор проекта KiCad: drain_watcher - датчик тока утечки автомобильного аккумулятора.

Плата-модуль на INA228 без своего микроконтроллера: внешний контроллер (ESP32 и т.п.)
подключается к гребёнке J1 по I2C (VCC, GND, SCL, SDA, ALERT). 2 слоя. Основной ток
по плате не идёт: шунт стоит на силовых шинах, плата снимает с него напряжение
(Kelvin) и напряжение аккумулятора.

    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/gen/build.py hardware

Схема и плата собираются из одного описания (PARTS ниже), разводка - координатами.
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv
import pcbnew
import pcbhelp
from pcbhelp import Builder, mm, tomm
import kigen

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), ".."))
NAME = "drain_watcher"
FCU, BCU = pcbnew.F_Cu, pcbnew.B_Cu
W, WP = 0.2, 0.4                           # сигнал / питание

# Узел измерения - как его расставили вручную в KiCad; гребёнка J1 - слева от INA228,
# подтяжки I2C - между ними. Справа вместо клеммы - четыре отверстия под провода
# (устройство цельное, провода впаиваются один раз).
TX, TY = 149.8, 117.6                       # колонка отверстий под провода, шаг 4.6 мм
UX, UY = 135.4, 122.0                       # INA228
HX, HY = 125.5, 129.0                       # гребёнка J1: вывод 1 (VCC) снизу, ряд вверх

# Контур - вплотную к деталям: слева по гребёнке J1 (подписи у неё - на обороте, справа
# от выводов), справа - по отверстиям под провода, сверху и снизу - по via и R3.
X0, X1 = 124.0, TX + 2.2
Y0, Y1 = 115.0, 133.3
BW, BH = X1 - X0, Y1 - Y0

# ------------------------------------------------------------------ детали
# ref: (libid, value, (fplib, fpname), {pin: net}, (x, y, rot))
R0603 = ("Resistor_SMD", "R_0603_1608Metric")
C0603 = ("Capacitor_SMD", "C_0603_1608Metric")

PARTS = {
    "U2": ("Sensor_Energy:INA228", "INA228AIDGSR", ("Package_SO", "MSOP-10_3x3mm_P0.5mm"),
           {"1": "GND", "2": "GND", "3": "ALERT", "4": "SDA", "5": "SCL", "6": "VCC",
            "7": "GND", "8": "VBUS_S", "9": "INN", "10": "INP"}, (UX, UY, 0)),
    # Гребёнка к внешнему контроллеру: 1 VCC (2.7...5.5 В), 2 GND, 3 SCL, 4 SDA, 5 ALERT.
    # Порядок выводов повторяет порядок у INA228 - дорожки идут без пересечений.
    "J1": ("Connector_Generic:Conn_01x05", "I2C", ("Connector_PinHeader_2.54mm", "PinHeader_1x05_P2.54mm_Vertical"),
           {"1": "VCC", "2": "GND", "3": "SCL", "4": "SDA", "5": "ALERT"}, (HX, HY, 180)),
    # Провода: 1 - SNS+ (шунт, сторона кузова), 2 - SNS- (шунт, сторона аккумулятора),
    # 3 - GND (отдельный провод на ту же сторону шунта), 4 - BAT+ (через предохранитель 1 А).
    # Отверстия 1.15 мм - под провод до 0.5 мм2.
    "J2": ("Connector_Generic:Conn_01x04", "WIRES",
           ("Connector_Wire", "SolderWire-0.5sqmm_1x04_P4.6mm_D0.9mm_OD2.1mm"),
           {"1": "SNS_P", "2": "SNS_N", "3": "GND", "4": "VBAT"}, (TX, TY, 270)),
    # --- вход измерения
    "D1": ("Device:D_TVS", "SMF24CA", ("Diode_SMD", "D_SOD-123F"), {"1": "SNS_P", "2": "SNS_N"}, (145.57, 118.86, 270)),
    "R1": ("Device:R", "10R", R0603, {"1": "INP", "2": "SNS_P"}, (UX + 6.6, 118.4, 0)),
    "R2": ("Device:R", "10R", R0603, {"1": "INN", "2": "SNS_N"}, (UX + 6.6, 120.4, 0)),
    "C1": ("Device:C", "100nF", C0603, {"1": "INP", "2": "INN"}, (UX + 4.3, 119.4, 270)),
    "R3": ("Device:R", "10k", ("Resistor_SMD", "R_1206_3216Metric"), {"1": "VBUS_S", "2": "VBAT"}, (143.51, 130.52, 270)),
    "D2": ("Device:D_Zener", "SMF24A", ("Diode_SMD", "D_SOD-123F"), {"1": "VBUS_S", "2": "GND"}, (145.58, 125.42, 270)),
    "C2": ("Device:C", "100nF", C0603, {"1": "VBUS_S", "2": "GND"}, (UX + 6.6, 122.8, 270)),
    "C3": ("Device:C", "100nF", C0603, {"1": "VCC", "2": "GND"}, (UX + 2.9, 125.3, 0)),
    # --- подтяжки I2C и ALERT к VCC (у многих плат контроллеров своих нет)
    "R4": ("Device:R", "4.7k", R0603, {"1": "SCL", "2": "VCC"}, (HX + 3.0, 124.75, 270)),
    "R5": ("Device:R", "4.7k", R0603, {"1": "SDA", "2": "VCC"}, (HX + 4.2, 120.55, 90)),
    "R6": ("Device:R", "10k", R0603, {"1": "ALERT", "2": "VCC"}, (HX + 2.5, 118.0, 90)),
}

b = Builder(layers=2)
for ref, (lid, val, (fl, fn), nets, (x, y, r)) in PARTS.items():
    b.place(ref, fl, fn, x, y, r, value=val)

# J1 и J2 - только отверстия: гребёнку 2.54 мм (или провода) впаивают по месту, а не на
# заводе. 3D-модели нет, в BOM и в файл установки (CPL) они не попадают.
NOPART = ("J1", "J2")
for _r in NOPART:
    _f = b.fps[_r]
    _f.Models().clear()
    _f.SetAttributes(_f.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)

# MSOP-10: пады 0.35 при шаге 0.5 оставляют 0.15 мм - меньше штатного зазора 0.2.
# Вывод корпуса VSSOP шириной 0.17...0.27 мм, пад 0.3 его с запасом накрывает.
for _p in b.fps["U2"].Pads():
    _s = _p.GetSize()
    _p.SetSize(pcbnew.VECTOR2I(_s.x, mm(0.3)))

# -------------------------------------------------------------------- схема
d = kigen.Design(NAME, "drain_watcher - INA228 I2C module, %.0fx%.0f mm, 2 layers" % (BW, BH), paper="A4")
d.prepare()
SCHAT = {"U2": (120, 90), "J1": (50, 90), "J2": (230, 90)}
small = [r for r in PARTS if r not in SCHAT]
for ref, (lid, val, (fl, fn), nets, _) in PARTS.items():
    at = SCHAT.get(ref)
    if at is None:
        i = small.index(ref)
        at = (60 + 30 * (i % 6), 150 + 30 * (i // 6))
    _pt = kigen.Part(ref, lid, val, "%s:%s" % (fl, fn), nets, at=at)
    if ref in NOPART:
        _pt.in_bom = False                  # только отверстия - деталью в BOM не считаются
    d.add(_pt)
# VCC приходит с гребёнки (пассивный вывод) - ERC нужен флаг источника; GND - тоже
for i, n in enumerate(["GND", "VCC"]):
    d.add(kigen.Part("#FLG%d" % i, "power:PWR_FLAG", "PWR_FLAG", "", {"1": n}, at=(240 + 25 * i, 170)))

FPLIB = NAME
for _pt in d.parts:
    if ":" in _pt.footprint:
        _pt.footprint = FPLIB + ":" + _pt.footprint.split(":", 1)[1]
os.makedirs(OUT, exist_ok=True)
d.write_sch(os.path.join(OUT, NAME + ".kicad_sch"))
for p in d.parts:
    if p.ref.startswith("#"):
        continue
    for pn, net in p.nets.items():
        b.setnet(p.ref, pn, net)

# ================================================================= разводка
P = b.padxy
T = lambda net, pts, w=W: b.track(net, pts, FCU, w)
B = lambda net, pts, w=W: b.track(net, pts, BCU, w)
V = lambda net, x, y, dia=0.6, drill=0.3: b.via(net, x, y, dia=dia, drill=max(drill, 0.3))


def pad_of(ref, net):
    """Пад детали с заданной цепью (для двухвыводных - тот, что нужен)."""
    for p_ in b.fps[ref].Pads():
        if p_.GetNetname() == net:
            q = p_.GetPosition()
            return (tomm(q.x), tomm(q.y))
    raise KeyError((ref, net))


# --- INA228: адрес 0x40 (A0 = A1 = GND) - via под корпусом
a1, a0 = P("U2", "1"), P("U2", "2")
T("GND", [a1, (a1[0] + 1.1, a1[1]), (a0[0] + 1.1, a0[1]), a0], W)
T("GND", [(a1[0] + 1.1, (a1[1] + a0[1]) / 2), (a1[0] + 1.7, (a1[1] + a0[1]) / 2)], W)
V("GND", a1[0] + 1.7, (a1[1] + a0[1]) / 2, 0.5, 0.25)
# GND вывод 7 -> C3, VS вывод 6 -> C3 -> via на нижний слой (VCC идёт по низу)
g7, vs = P("U2", "7"), P("U2", "6")
c3g, c3v = pad_of("C3", "GND"), pad_of("C3", "VCC")
T("GND", [g7, (g7[0] + 1.2, g7[1]), (g7[0] + 1.2, c3g[1] - 0.5), c3g], W)
T("GND", [c3g, (c3g[0] + 1.2, c3g[1])], W)
V("GND", c3g[0] + 1.2, c3g[1])
YVC = HY                                    # VCC по нижнему слою - на уровне вывода 1 J1
T("VCC", [vs, (vs[0], c3v[1]), c3v, (c3v[0], c3v[1] + 1.4)], W)
V("VCC", c3v[0], c3v[1] + 1.4)
B("VCC", [(c3v[0], c3v[1] + 1.4), (c3v[0], YVC), P("J1", "1")], WP)

# --- I2C и ALERT: от гребёнки горизонталями, у INA228 - ступенькой на её выводы
al, sda, scl = P("U2", "3"), P("U2", "4"), P("U2", "5")
ja, jd, jc = P("J1", "5"), P("J1", "4"), P("J1", "3")
T("ALERT", [ja, (UX - 3.6, ja[1]), (UX - 3.6, al[1]), al], W)
T("SDA", [jd, (UX - 4.3, jd[1]), (UX - 4.3, sda[1]), sda], W)
T("SCL", [jc, (UX - 5.0, jc[1]), (UX - 5.0, scl[1]), scl], W)
# подтяжки: свободный пад - на VCC через via; по низу - общая шина VCC
XBV = HX + 1.6                               # вертикаль шины VCC по нижнему слою
r6, r5, r4 = pad_of("R6", "VCC"), pad_of("R5", "VCC"), pad_of("R4", "VCC")
v6 = (r6[0], r6[1] - 1.3)
v5 = (r5[0] + 1.1, r5[1])
v4 = (r4[0], r4[1] + 1.35)
T("VCC", [r6, v6], W); V("VCC", *v6)
T("VCC", [r5, v5], W); V("VCC", *v5)
T("VCC", [r4, v4], W); V("VCC", *v4)
B("VCC", [(XBV, YVC), (XBV, v6[1]), v6], 0.3)
B("VCC", [(XBV, v5[1]), v5], 0.3)
B("VCC", [(XBV, v4[1]), v4], 0.3)

# --- вход измерения: Kelvin-пара от клеммы через RC-фильтр
inp, inn = P("U2", "10"), P("U2", "9")
r1i, r2i = pad_of("R1", "INP"), pad_of("R2", "INN")
c1p, c1n = pad_of("C1", "INP"), pad_of("C1", "INN")
T("INP", [r1i, (inp[0] + 1.3, r1i[1]), (inp[0] + 1.3, inp[1]), inp], W)
T("INP", [(c1p[0], r1i[1]), c1p], W)
T("INN", [r2i, (c1n[0], r2i[1]), (c1n[0], inn[1]), inn], W)
j1, j2 = P("J2", "1"), P("J2", "2")
r1s, r2s = pad_of("R1", "SNS_P"), pad_of("R2", "SNS_N")
T("SNS_P", [j1, (UX + 9.0, j1[1]), (UX + 9.0, r1s[1]), r1s], W)
T("SNS_N", [j2, (UX + 10.0, j2[1]), (UX + 10.0, r2s[1]), r2s], W)
d1p, d1n = pad_of("D1", "SNS_P"), pad_of("D1", "SNS_N")
T("SNS_P", [(d1p[0], j1[1]), d1p], W)
T("SNS_N", [(d1n[0], j2[1]), d1n], W)

# --- напряжение аккумулятора: BAT+ -> 10k -> TVS + 100nF -> VBUS INA228
j4 = P("J2", "4")
r3b, r3s = pad_of("R3", "VBAT"), pad_of("R3", "VBUS_S")
vb = P("U2", "8")
T("VBAT", [j4, r3b], WP)
XVS = r3s[0]                                 # полоса VBUS_S - прямо над R3
T("VBUS_S", [r3s, (XVS, r3s[1]), (XVS, vb[1]), vb], W)
d2v = pad_of("D2", "VBUS_S")
T("VBUS_S", [d2v, (XVS, d2v[1])], W)
g = pad_of("D2", "GND")
T("GND", [g, (g[0] + 1.2, g[1] - 0.8)], W)
V("GND", g[0] + 1.2, g[1] - 0.8)
g = pad_of("C2", "GND")
T("GND", [g, (g[0], g[1] + 1.3)], W)
V("GND", g[0], g[1] + 1.3)

# -------------------------------------------------- контур, полигоны, шелк
b.edge_rect(X0 + BW / 2, Y0 + BH / 2, BW, BH, 1.0)
b.zone("GND", FCU, X0 + BW / 2, Y0 + BH / 2, BW - 0.6, BH - 0.6)
b.zone("GND", BCU, X0 + BW / 2, Y0 + BH / 2, BW - 0.6, BH - 0.6)

SZ, TH = 0.8, 0.15
BS = pcbnew.B_SilkS
# Подписи проводов - повёрнуты на 90 (так их развернули вручную в KiCad) и стоят узкой
# полосой между диодами и отверстиями, с обеих сторон.
# Подписи гребёнки - только на обороте, справа от выводов: слева от J1 плата обрезана.
for i, lbl in enumerate(("SNS+", "SNS-", "GND", "BAT+")):
    x, y = P("J2", str(i + 1))
    # BAT+ чуть выше и левее - у нижнего края платы (выставлено вручную)
    dx, dy = (-2.28, -0.44) if lbl == "BAT+" else (-2.1, 0.0)
    b.text(lbl, x + dx, y + dy, size=SZ, thick=TH, rot=90)
    b.text(lbl, x + dx, y + dy, layer=BS, size=0.9, thick=0.18, rot=90, mirror=True)
for i, lbl in enumerate(("VCC", "GND", "SCL", "SDA", "ALERT")):
    x, y = P("J1", str(i + 1))
    dx = 3.79 if lbl == "ALERT" else 3.24   # длинное ALERT - чуть правее, чтобы не лезть на пад
    b.text(lbl, x + dx, y, layer=BS, size=SZ, thick=TH, mirror=True)


def _bot_obstacles():
    obs = []
    for _fp in b.b.GetFootprints():
        for _p in _fp.Pads():
            ls = _p.GetLayerSet()
            if ls.Contains(pcbnew.B_Cu) or _p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                bb = _p.GetBoundingBox()
                obs.append((tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())))
    # via закрыты маской (tented) - шелк поверх них печатается, они не помеха
    for _d in b.b.GetDrawings():
        if _d.GetClass() == "PCB_TEXT" and _d.GetLayer() == BS:
            bb = _d.GetBoundingBox()            # с учётом поворота
            obs.append((tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())))
    return obs


def back_block(lines, anchor, pitch=1.25, size=SZ, thick=TH, first=None):
    """Столбец строк на B.Silkscreen по центру x; ищет ближайшее к anchor свободное место."""
    obs = _bot_obstacles()
    ts = []
    for i, ln in enumerate(lines):
        sz, th = (first if (first and i == 0) else (size, thick))
        ts.append(b.text(ln, 0, 0, layer=BS, size=sz, thick=th, mirror=True))
    # шаг строк - не меньше габарита надписи, иначе соседние строки слипаются
    hs = [tomm(kicadenv.textbox(t).GetHeight()) for t in ts]
    offs = [0.0]
    for i in range(1, len(ts)):
        offs.append(offs[-1] + max(pitch, (hs[i - 1] + hs[i]) / 2 + 0.1))
    cands = sorted(((X0 + 1.0 + 0.25 * i, Y0 + 1.0 + 0.25 * j)
                    for i in range(int((BW - 2) / 0.25)) for j in range(int((BH - 2) / 0.25))),
                   key=lambda p_: (p_[0] - anchor[0]) ** 2 + (p_[1] - anchor[1]) ** 2)
    for cx, cy in cands:
        ok = True
        boxes = []
        for i, t in enumerate(ts):
            t.SetPosition(pcbnew.VECTOR2I(mm(cx), mm(cy + offs[i])))
            bb = kicadenv.textbox(t)
            bx = (tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom()))
            if bx[0] < X0 + 0.6 or bx[2] > X1 - 0.6 or bx[1] < Y0 + 0.6 or bx[3] > Y1 - 0.6                     or any(_hit(bx, o, 0.25) for o in obs):
                ok = False
                break
        if ok:
            return (cx, cy)
    for t in ts:
        b.b.Remove(t)
    print("  на обратной стороне нет места для блока:", lines[0])
    return None


def _hit(a, c, m=0.15):
    return a[0] < c[2] + m and c[0] < a[2] + m and a[1] < c[3] + m and c[1] < a[3] + m


# Легенда номиналов: детали с одинаковым номиналом - через запятую, затем номинал.
_byval = {}
for _r, (_lid, _val, _fpid, _n, _xy) in PARTS.items():
    if _r.startswith("J"):                  # разъёмы подписаны у самих выводов
        continue
    _byval.setdefault(_val, []).append(_r)
_key = lambda r: (re.match(r"[A-Z]+", r).group(0), int(re.search(r"\d+", r).group(0)))
LEGEND = ["%s: %s" % (",".join(sorted(rs, key=_key)), v)
          for v, rs in sorted(_byval.items(), key=lambda kv: _key(sorted(kv[1], key=_key)[0]))]


def back_group(items, anchor):
    """Группа надписей на B.Silkscreen с относительными смещениями; ищет ближайшее к
    anchor место, где ни одна надпись не ложится на пад, via или отверстие.
    items: (текст, dx, dy, угол, размер, толщина)."""
    obs = _bot_obstacles()
    ts = [(b.text(t, 0, 0, layer=BS, size=sz, thick=th, rot=a, mirror=True), dx, dy)
          for t, dx, dy, a, sz, th in items]
    cands = sorted(((X0 + 1.0 + 0.25 * i, Y0 + 1.0 + 0.25 * j)
                    for i in range(int((BW - 2) / 0.25)) for j in range(int((BH - 2) / 0.25))),
                   key=lambda p_: (p_[0] - anchor[0]) ** 2 + (p_[1] - anchor[1]) ** 2)
    for cx, cy in cands:
        ok = True
        for t, dx, dy in ts:
            t.SetPosition(pcbnew.VECTOR2I(mm(cx + dx), mm(cy + dy)))
            bb = t.GetBoundingBox()             # с учётом поворота, в отличие от textbox
            bx = (tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom()))
            if bx[0] < X0 + 0.6 or bx[2] > X1 - 0.6 or bx[1] < Y0 + 0.6 or bx[3] > Y1 - 0.6                     or any(_hit(bx, o, 0.2) for o in obs):
                ok = False
                break
        if ok:
            return (cx, cy)
    xs, ys = [], []
    for t, dx, dy in ts:
        t.SetPosition(pcbnew.VECTOR2I(mm(anchor[0] + dx), mm(anchor[1] + dy)))
        bb = t.GetBoundingBox()
        xs += [tomm(bb.GetLeft()), tomm(bb.GetRight())]
        ys += [tomm(bb.GetTop()), tomm(bb.GetBottom())]
    print("  на обратной стороне нет места для группы надписей %.1f x %.1f мм (%s)"
          % (max(xs) - min(xs), max(ys) - min(ys), items[0][0]))
    return None


def _size(txt, sz, th, a=0):
    t = b.text(txt, 0, 0, layer=BS, size=sz, thick=th, rot=a, mirror=True)
    bb = kicadenv.textbox(t)
    w, h = tomm(bb.GetWidth()), tomm(bb.GetHeight())
    b.b.Remove(t)
    return w, h


# Обратная сторона - компоновка, выставленная вручную в KiCad: легенда номиналов
# строками по центру, под ней ASTechLab и DRAIN WATCHER. Текст легенды берётся из
# PARTS, так что при смене номинала он обновится сам; места - фиксированные.
LSZ, LTH = 1.0, 0.18
_legend = sorted(LEGEND, key=lambda l: (not l.startswith("U"), l))   # микросхема - первой
LEG_Y = (116.805, 118.185, 119.67, 121.12, 122.47, 123.92, 125.3)
assert len(_legend) <= len(LEG_Y), "легенда выросла - добавьте строк в LEG_Y"
for _l, _y in zip(_legend, LEG_Y):
    b.text(_l, 138.3, _y, layer=BS, size=LSZ, thick=LTH, mirror=True)
b.text("ASTechLab", 138.46, 127.78, layer=BS, size=2.0, thick=0.5, mirror=True)
b.text("DRAIN WATCHER", 137.52, 131.16, layer=BS, size=1.5, thick=0.375, mirror=True)


def stack(lines, anchor, rot=0, front=False):
    its, y = [], 0.0
    for t_, sz_, th_ in lines:
        h_ = _size(t_, sz_, th_)[1]
        if rot:
            its.append((t_, y + h_ / 2, 0.0, rot, sz_, th_))
        else:
            its.append((t_, 0.0, y + h_ / 2, 0, sz_, th_))
        y += h_ + 0.15
    return (front_group if front else back_group)(its, anchor)


def front_group(items, anchor):
    """То же, что back_group, но на лицевой стороне: заняты пады, корпуса деталей и надписи."""
    obs = []
    for _fp in b.b.GetFootprints():
        for _p in _fp.Pads():
            if _p.GetLayerSet().Contains(FCU) or _p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                bb = _p.GetBoundingBox()
                obs.append((tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())))
        _cy = _fp.GetCourtyard(pcbnew.F_CrtYd)
        if _cy.OutlineCount():
            bb = _cy.BBox()
            obs.append((tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())))
    for _d in b.b.GetDrawings():
        if _d.GetClass() == "PCB_TEXT" and _d.GetLayer() == pcbnew.F_SilkS:
            bb = _d.GetBoundingBox()
            obs.append((tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())))
    ts = [(b.text(t, 0, 0, size=sz, thick=th, rot=a), dx, dy) for t, dx, dy, a, sz, th in items]
    cands = sorted(((X0 + 1.0 + 0.25 * i, Y0 + 1.0 + 0.25 * j)
                    for i in range(int((BW - 2) / 0.25)) for j in range(int((BH - 2) / 0.25))),
                   key=lambda p_: (p_[0] - anchor[0]) ** 2 + (p_[1] - anchor[1]) ** 2)
    for cx, cy in cands:
        ok = True
        for t, dx, dy in ts:
            t.SetPosition(pcbnew.VECTOR2I(mm(cx + dx), mm(cy + dy)))
            bb = t.GetBoundingBox()
            bx = (tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom()))
            if bx[0] < X0 + 0.6 or bx[2] > X1 - 0.6 or bx[1] < Y0 + 0.6 or bx[3] > Y1 - 0.6 \
                    or any(_hit(bx, o, 0.2) for o in obs):
                ok = False
                break
        if ok:
            return (cx, cy)
    print("  на лицевой стороне нет места для надписи:", items[0][0])
    return None


# Лицевая сторона: правило для провода BAT+ и шунт, под который рассчитана плата.
# Шкала - до ~35 А при незаведённой машине: шунт 30 А / 75 мВ = 2.5 мОм, INA228 в
# широком диапазоне меряет до ~65 А, в узком (до ~16 А) - с шагом ~31 мкА.
b.text("BAT+ via 1A fuse", 135.5, 116.39, size=SZ, thick=TH)
b.text("4 terminal shunt\n2.5 mOhm 30A 75mV", 135.36, 130.0, size=SZ, thick=TH)
print("легенда номиналов: %d строк" % len(LEGEND))

# Обозначения деталей: шрифт по нормам JLCPCB (0.8 / 0.15). Место для каждого ищется
# перебором вокруг детали: занятыми считаются пады, корпуса (courtyard) других деталей,
# уже поставленные надписи и полоса у края платы.
def _box(item):
    bb = kicadenv.textbox(item) if item.GetClass() in ("PCB_TEXT", "PCB_FIELD") else item.GetBoundingBox()
    return (tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom()))


def _hit(a, c, m=0.15):
    return a[0] < c[2] + m and c[0] < a[2] + m and a[1] < c[3] + m and c[1] < a[3] + m


OBST = []
for _fp in b.b.GetFootprints():
    for _p in _fp.Pads():
        OBST.append(("pad", _box(_p)))
    _cy = _fp.GetCourtyard(pcbnew.F_CrtYd)
    if _cy.OutlineCount():
        _bb = _cy.BBox()
        OBST.append(("crtyd", (tomm(_bb.GetLeft()), tomm(_bb.GetTop()),
                                           tomm(_bb.GetRight()), tomm(_bb.GetBottom()))))
for _d in b.b.GetDrawings():
    if _d.GetClass() == "PCB_TEXT" and _d.GetLayer() == pcbnew.F_SilkS:
        OBST.append(("text", _box(_d)))
# дорожки шелку не мешают, но via - открытая медь под маской: шелк поверх неё плывёт
for _t in b.b.GetTracks():
    if _t.GetClass() == "PCB_VIA":
        OBST.append(("via", _box(_t)))
# Положения обозначений, выставленные вручную в KiCad (x, y, угол[, размер])
REF_FIX = {"C1": (137.78, 119.25, 0), "C2": (140.39, 123.22, 0), "C3": (135.175, 125.3, 0),
           "D1": (145.57, 121.84, 0), "D2": (145.63, 128.31, 0),
           "R1": (142.08, 116.76, 0), "R2": (140.26, 121.71, 0), "R3": (145.62, 130.61, 0),
           "R4": (130.11, 124.77, 0), "R5": (131.42, 120.68, 0), "R6": (129.79, 117.67, 0),
           "U2": (135.4, 119.305, 0), "J1": (125.49, 131.69, 0)}


def place_ref(fp):
    t = fp.Reference()
    t.SetTextSize(pcbnew.VECTOR2I(mm(SZ), mm(SZ)))
    t.SetTextThickness(mm(TH))
    ref = fp.GetReference()
    if ref.startswith("H") or ref == "J2":      # у проводов - свои подписи
        t.SetVisible(False)
        return
    t.SetVisible(True)
    if ref in REF_FIX:
        x, y, a = REF_FIX[ref][:3]
        if len(REF_FIX[ref]) > 3:
            t.SetTextSize(pcbnew.VECTOR2I(mm(REF_FIX[ref][3]), mm(REF_FIX[ref][3])))
        t.SetTextAngleDegrees(a)
        t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        OBST.append(("text", _box(t)))
        return
    cy = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
    l, tp, r, bt = tomm(cy.GetLeft()), tomm(cy.GetTop()), tomm(cy.GetRight()), tomm(cy.GetBottom())
    cx, cyy = (l + r) / 2, (tp + bt) / 2
    cands = []
    for d in (0.0, 0.4, 0.8, 1.2, 1.8, 2.5):
        cands += [(cx, tp - 0.5 - d, 0), (cx, bt + 0.5 + d, 0), (l - 0.6 - d, cyy, 90),
                  (r + 0.6 + d, cyy, 90), (l - 1.6 - d, cyy, 0), (r + 1.6 + d, cyy, 0),
                  (l - 1.2 - d, tp - 0.3, 0), (r + 1.2 + d, tp - 0.3, 0),
                  (l - 1.2 - d, bt + 0.3, 0), (r + 1.2 + d, bt + 0.3, 0)]
    # сначала - не заходя на корпуса соседей, потом - разрешая (шелк над корпусом
    # соседа хотя бы виден до монтажа), но никогда поверх падов, via и чужих надписей
    for strict in (True, False):
        for x, y, a in cands:
            t.SetTextAngleDegrees(a)
            t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            bx = _box(t)
            if bx[0] < X0 + 0.5 or bx[2] > X1 - 0.5 or bx[1] < Y0 + 0.5 or bx[3] > Y1 - 0.5:
                continue
            if any(_hit(bx, o) for kind, o in OBST if strict or kind != "crtyd"):
                continue
            OBST.append(("text", bx))
            return
    print("  нет места для обозначения", ref, "- скрыто")
    t.SetVisible(False)


for _fp in sorted(b.b.GetFootprints(), key=lambda f: f.GetReference()):
    place_ref(_fp)

# J2 - это уже не клемма, а четыре отверстия под провода, у каждого своя подпись.
# Надпись ${REFERENCE} на слое сборки (F.Fab) между отверстиями только путает - убираем.
# (в самом конце: после Remove() SWIG в KiCad 10 теряет типы у прокси-объектов)
for _g in list(b.fps["J2"].GraphicalItems()):
    if _g.GetClass() == "PCB_TEXT" and _g.GetLayer() == pcbnew.F_Fab:
        b.fps["J2"].Remove(_g)

# ------------------------------------------------ своя библиотека футпринтов
LIBDIR = os.path.join(OUT, FPLIB + ".pretty")
os.makedirs(LIBDIR, exist_ok=True)
for _f in os.listdir(LIBDIR):
    if _f.endswith(".kicad_mod"):
        os.remove(os.path.join(LIBDIR, _f))
_saved = set()
for _fp in b.b.GetFootprints():
    _nm = str(_fp.GetFPID().GetLibItemName())
    if _nm not in _saved:
        try:
            _c = pcbnew.Cast_to_FOOTPRINT(_fp.Duplicate(False))
        except TypeError:
            _c = _fp.Duplicate()
        if _c.IsFlipped():
            _c.Flip(_c.GetPosition(), False)
        _c.SetPosition(pcbnew.VECTOR2I(0, 0))
        _c.SetOrientationDegrees(0)
        _c.SetReference("REF**")
        _c.SetValue(_nm)
        pcbhelp.footprint_save(LIBDIR, _c)
        _saved.add(_nm)
    _fp.SetFPID(pcbnew.LIB_ID(FPLIB, _nm))
print("библиотека проекта: %d футпринтов" % len(_saved))
with open(os.path.join(OUT, "fp-lib-table"), "w") as _t:
    _t.write('(fp_lib_table\n  (version 7)\n'
             '  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.pretty")(options "")(descr "Footprints used by this board"))\n)\n'
             % (FPLIB, FPLIB))

# Свободные выводы помечены в схеме крестиком no_connect, у их падов цепи нет -
# схема и плата совпадают без искусственных имён unconnected-(...).

b.finish(os.path.join(OUT, NAME + ".kicad_pcb"))

# Правила проекта - те, под которые плата разведена
_pro = os.path.join(OUT, NAME + ".kicad_pro")
_d = json.load(open(_pro)) if os.path.exists(_pro) else {"meta": {"filename": NAME + ".kicad_pro", "version": 3}}
_ns = _d.setdefault("net_settings", {})
_cls = _ns.setdefault("classes", [])
if not any(c.get("name") == "Default" for c in _cls):
    _cls.append({"name": "Default"})
for _c in _cls:
    if _c.get("name") == "Default":
        _c.update({"clearance": 0.2, "track_width": W, "via_diameter": 0.6, "via_drill": 0.3})
_ds = _d.setdefault("board", {}).setdefault("design_settings", {})
_ds.setdefault("rules", {}).update({"min_track_width": 0.15, "min_clearance": 0.2,
                                     "min_via_diameter": 0.45, "min_through_hole_diameter": 0.25,
                                     "min_copper_edge_clearance": 0.3,
                                     "min_via_annular_width": 0.1})
json.dump(_d, open(_pro, "w"), indent=2)
print("OK ->", OUT)
