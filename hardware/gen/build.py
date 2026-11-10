#!/usr/bin/env python3
"""Генератор проекта KiCad: drain_watcher - логгер тока утечки автомобильного аккумулятора.

Плата 70 x 50 мм, 2 слоя. Основной ток по плате не идёт: шунт стоит на силовых шинах,
плата только снимает с него напряжение (Kelvin) и напряжение аккумулятора.

    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/gen/build.py hardware

Схема и плата собираются из одного описания (PARTS ниже), разводка - координатами.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv
import pcbnew
import pcbhelp
from pcbhelp import Builder, mm, tomm
import kigen

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), ".."))
NAME = "drain_watcher"
X0, Y0, BW, BH = 100.0, 100.0, 70.0, 50.0
X1, Y1 = X0 + BW, Y0 + BH
FCU, BCU = pcbnew.F_Cu, pcbnew.B_Cu
W, WN, WP = 0.2, 0.15, 0.4                 # сигнал / узкая (USB, CC) / питание

# ------------------------------------------------------------------ детали
# ref: (libid, value, (fplib, fpname), {pin: net}, (x, y, rot))
R0603 = ("Resistor_SMD", "R_0603_1608Metric")
C0603 = ("Capacitor_SMD", "C_0603_1608Metric")
C0805 = ("Capacitor_SMD", "C_0805_2012Metric")
SW = ("Button_Switch_SMD", "SW_SPST_SKQG_WithoutStem")

# Модуль повёрнут антенной к левому краю: ряд выводов 1-14 смотрит вниз (питание, EN,
# USB), ряд 27-40 - вверх (кнопки, светодиод), ряд 15-26 - вправо, к INA228.
MX, MY = 112.75, 122.0
JX = 122.5                                  # ось USB-C: D- (A7) встаёт под вывод 13 модуля
JY = 145.9
UX, UY = 140.0, 122.0                       # INA228
TX = 164.0                                  # колонка винтовой клеммы

ESP_NETS = {"1": "GND", "40": "GND", "41": "GND", "2": "+3V3", "3": "EN",
            "13": "USB_DM", "14": "USB_DP",
            "21": "SDA",        # IO13
            "20": "SCL",        # IO12
            # ALERT - на IO21 (вывод 23), а не на соседний IO14: тогда SDA не оказывается
            # в середине жгута и подтяжке SDA остаётся место. Подтяжка ALERT -
            # внутренняя (open-drain, сигнал медленный).
            "23": "ALERT",      # IO21
            "27": "BOOT",       # IO0
            "34": "MARK1",      # IO41
            "31": "MARK2",      # IO38
            "35": "LED"}        # IO42

PARTS = {
    "U1": ("RF_Module:ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1-N16R8", ("RF_Module", "ESP32-S3-WROOM-1"),
           ESP_NETS, (MX, MY, 90)),
    "U2": ("Sensor_Energy:INA228", "INA228AIDGSR", ("Package_SO", "MSOP-10_3x3mm_P0.5mm"),
           {"1": "GND", "2": "GND", "3": "ALERT", "4": "SDA", "5": "SCL", "6": "+3V3",
            "7": "GND", "8": "VBUS_S", "9": "INN", "10": "INP"}, (UX, UY, 0)),
    "U3": ("Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", ("Package_TO_SOT_SMD", "SOT-23-5"),
           {"1": "VBUS", "2": "GND", "3": "VBUS", "5": "+3V3"}, (114.5, 137.8, 180)),
    "J1": ("Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", ("Connector_USB", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
           {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
            "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
            "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP",
            "A7": "USB_DM", "B7": "USB_DM", "SH": "GND"}, (JX, JY, 0)),
    # Клемма: 1 - SNS+ (шунт, сторона кузова), 2 - SNS- (шунт, сторона аккумулятора),
    # 3 - GND (отдельный провод на ту же сторону шунта), 4 - BAT+ (через предохранитель 1 А)
    "J2": ("Connector_Generic:Conn_01x04", "SHUNT/BAT",
           ("TerminalBlock_Phoenix", "TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal"),
           {"1": "SNS_P", "2": "SNS_N", "3": "GND", "4": "VBAT"}, (TX, 113.0, 270)),
    # --- вход измерения
    "D1": ("Device:D_TVS", "SMF24CA", ("Diode_SMD", "D_SOD-123F"), {"1": "SNS_P", "2": "SNS_N"}, (156.0, 115.54, 270)),
    "R1": ("Device:R", "10R", R0603, {"1": "INP", "2": "SNS_P"}, (146.6, 118.4, 0)),
    "R2": ("Device:R", "10R", R0603, {"1": "INN", "2": "SNS_N"}, (146.6, 120.4, 0)),
    "C1": ("Device:C", "100nF", C0603, {"1": "INP", "2": "INN"}, (144.3, 119.4, 270)),
    "R3": ("Device:R", "10k", ("Resistor_SMD", "R_1206_3216Metric"), {"1": "VBUS_S", "2": "VBAT"}, (156.0, 128.24, 0)),
    "D2": ("Device:D_Zener", "SMF24A", ("Diode_SMD", "D_SOD-123F"), {"1": "VBUS_S", "2": "GND"}, (152.2, 129.8, 270)),
    "C2": ("Device:C", "100nF", C0603, {"1": "VBUS_S", "2": "GND"}, (146.6, 122.8, 270)),
    "C3": ("Device:C", "100nF", C0603, {"1": "+3V3", "2": "GND"}, (142.9, 125.3, 0)),
    "R4": ("Device:R", "4.7k", R0603, {"1": "SCL", "2": "+3V3"}, (132.0, 123.6, 270)),
    "R5": ("Device:R", "4.7k", R0603, {"1": "SDA", "2": "+3V3"}, (130.0, 120.5, 90)),
    # --- питание и ESP32
    "C4": ("Device:C", "10uF", C0805, {"1": "VBUS", "2": "GND"}, (118.4, 136.85, 90)),
    "C5": ("Device:C", "10uF", C0805, {"1": "+3V3", "2": "GND"}, (111.0, 139.7, 270)),
    "C6": ("Device:C", "10uF", C0805, {"1": "GND", "2": "+3V3"}, (107.81, 136.0, 0)),
    "C7": ("Device:C", "100nF", C0603, {"1": "GND", "2": "+3V3"}, (107.985, 133.6, 0)),
    "C8": ("Device:C", "1uF", C0603, {"1": "EN", "2": "GND"}, (112.3, 133.6, 270)),
    "R7": ("Device:R", "10k", R0603, {"1": "EN", "2": "+3V3"}, (114.3, 133.6, 270)),
    "R9": ("Device:R", "5.1k", R0603, {"1": "CC1", "2": "GND"}, (JX - 1.25, 136.0, 90)),
    "R10": ("Device:R", "5.1k", R0603, {"1": "CC2", "2": "GND"}, (JX + 1.75, 136.0, 90)),
    # --- кнопки и светодиод
    "SW1": ("Switch:SW_Push", "MARK1", SW, {"1": "GND", "2": "MARK1"}, (112.0, 106.0, 0)),
    "SW2": ("Switch:SW_Push", "MARK2", SW, {"1": "GND", "2": "MARK2"}, (123.0, 106.0, 0)),
    "SW3": ("Switch:SW_Push", "BOOT", SW, {"1": "GND", "2": "BOOT"}, (134.0, 106.0, 0)),
    "R8": ("Device:R", "1k", R0603, {"1": "LED_A", "2": "LED"}, (112.2, 110.6, 0)),
    "D3": ("Device:LED", "LED", ("LED_SMD", "LED_0805_2012Metric"), {"1": "GND", "2": "LED_A"}, (108.9, 110.6, 0)),
}
# Левый край целиком - запретная зона антенны (она в футпринте модуля): винт там
# испортил бы диаграмму. Отверстия - в правых углах, слева снизу и сверху за кнопками.
HOLES = [(147.0, 104.0), (166.0, 104.0), (110.5, 146.5), (166.0, 146.0)]

b = Builder(layers=2)
for ref, (lid, val, (fl, fn), nets, (x, y, r)) in PARTS.items():
    b.place(ref, fl, fn, x, y, r, value=val)
for i, (x, y) in enumerate(HOLES, 1):
    b.place("H%d" % i, "MountingHole", "MountingHole_3.2mm_M3", x, y, 0, value="M3")

# JLCPCB для 2 слоёв сверлит от 0.3 мм. Тепловые отверстия под модулем в библиотечном
# футпринте - 0.2 мм; раздаём до 0.3 (пад 0.6, пояс 0.15 - в норме).
for _p in b.fps["U1"].Pads():
    if _p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and tomm(_p.GetDrillSize().x) < 0.3:
        _p.SetDrillSize(pcbnew.VECTOR2I(mm(0.3), mm(0.3)))
# MSOP-10: пады 0.35 при шаге 0.5 оставляют 0.15 мм - меньше штатного зазора 0.2.
# Вывод корпуса VSSOP шириной 0.17...0.27 мм, пад 0.3 его с запасом накрывает.
for _p in b.fps["U2"].Pads():
    _s = _p.GetSize()
    _p.SetSize(pcbnew.VECTOR2I(_s.x, mm(0.3)))

# -------------------------------------------------------------------- схема
d = kigen.Design(NAME, "drain_watcher - INA228 + ESP32-S3, 70x50 mm, 2 layers", paper="A3")
d.prepare()
SCHAT = {"U1": (80, 110), "U2": (230, 90), "U3": (230, 200), "J1": (80, 220), "J2": (330, 90)}
GX, GY, GDX, GDY, GROWS = 160.0, 40.0, 30.0, 30.0, 8
small = [r for r in PARTS if r not in SCHAT]
for ref, (lid, val, (fl, fn), nets, _) in PARTS.items():
    at = SCHAT.get(ref)
    if at is None:
        i = small.index(ref)
        at = (300 + GDX * (i // GROWS), 140 + GDY * (i % GROWS))
    d.add(kigen.Part(ref, lid, val, "%s:%s" % (fl, fn), nets, at=at))
for i in range(len(HOLES)):
    _h = kigen.Part("H%d" % (i + 1), "Mechanical:MountingHole", "M3",
                    "MountingHole:MountingHole_3.2mm_M3", {}, at=(400 + 20 * i, 270))
    _h.in_bom = False                       # у футпринта отверстия стоит "не в BOM"
    d.add(_h)
# +3V3 флаг не нужен: выход AP2112K сам power_out, второй источник ERC считает конфликтом
for i, n in enumerate(["GND", "VBUS"]):
    d.add(kigen.Part("#FLG%d" % i, "power:PWR_FLAG", "PWR_FLAG", "", {"1": n}, at=(160 + 30 * i, 270)))

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


# --- USB-C: пары D+/D- сведены перемычками на нижнем слое (пады чередуются через 0.5 мм)
PY = P("J1", "A6")[1]
YDP, YDM = PY - 2.4, PY - 1.2
for pn in ("A6", "B6"):
    x = P("J1", pn)[0]
    T("USB_DP", [(x, PY), (x, YDP)], WN)
    V("USB_DP", x, YDP, 0.45, 0.25)
for pn in ("A7", "B7"):
    x = P("J1", pn)[0]
    T("USB_DM", [(x, PY), (x, YDM)], WN)
    V("USB_DM", x, YDM, 0.45, 0.25)
B("USB_DP", [(P("J1", "A6")[0], YDP), (P("J1", "B6")[0], YDP)], WN)
B("USB_DM", [(P("J1", "B7")[0], YDM), (P("J1", "A7")[0], YDM)], WN)
p13, p14 = P("U1", "13"), P("U1", "14")
xm, xp = P("J1", "A7")[0], P("J1", "B6")[0]
T("USB_DM", [(xm, YDM), (xm, p13[1] + 1.0), (p13[0], p13[1] + 0.6), p13], WN)
T("USB_DP", [(xp, YDP), (xp, p14[1] + 2.85), (p14[0], p14[1] + 2.1), p14], WN)
# CC: вверх к резисторам 5.1k, их земля - via над ними
for pn, net, r in (("A5", "CC1", "R9"), ("B5", "CC2", "R10")):
    x = P("J1", pn)[0]
    T(net, [(x, PY), pad_of(r, net)], WN)
    g = pad_of(r, "GND")
    T("GND", [g, (g[0], g[1] - 1.7)], W)
    V("GND", g[0], g[1] - 1.7)
# земля разъёма - на ближайшие пады экрана (они сквозные и сидят на полигонах)
for pn, sh in (("A1", -1), ("A12", 1)):
    x = P("J1", pn)[0]
    T("GND", [(x, PY), (JX + sh * 4.32, PY + 0.45)], WP)
# VBUS: левый пад вверх, правый - вверх и через нижний слой к левому
YVB = 137.8
xl, xr = P("J1", "A4")[0], P("J1", "A9")[0]
T("VBUS", [(xl, PY), (xl, YVB)], WP)
V("VBUS", xl, YVB)
T("VBUS", [(xr, PY), (xr, PY - 1.25), (xr + 0.65, PY - 1.9), (xr + 0.65, YVB)], WP)
V("VBUS", xr + 0.65, YVB)
B("VBUS", [(xl, YVB), (xr + 0.65, YVB)], WP)
# VBUS -> C4 -> U3 (VIN и EN вместе)
vin, ven = P("U3", "1"), P("U3", "3")
XJ = vin[0] + 1.15
T("VBUS", [(xl, YVB), (XJ, YVB)], WP)
T("VBUS", [(XJ, ven[1]), (XJ, vin[1])], WP)
T("VBUS", [ven, (XJ, ven[1])], WP)
T("VBUS", [vin, (XJ, vin[1])], WP)
g = pad_of("C4", "GND")
T("GND", [g, (g[0], g[1] - 1.4)], W)
V("GND", g[0], g[1] - 1.4)
# земля стабилизатора - via под корпусом
g = P("U3", "2")
T("GND", [g, (114.5, g[1])], W)
V("GND", 114.5, g[1], 0.5, 0.25)

# --- +3V3: выход стабилизатора -> C5 -> вверх по x=108.76 через C6, C7 к выводу 2 модуля
vo = P("U3", "5")
p2 = P("U1", "2")
T("+3V3", [vo, (p2[0], vo[1]), p2], WP)
g = pad_of("C5", "GND")
T("GND", [g, (g[0], g[1] + 1.25)], W)
V("GND", g[0], g[1] + 1.25)
g = pad_of("C6", "GND")
T("GND", [g, (g[0], g[1] + 1.4)], W)
V("GND", g[0], g[1] + 1.4)
g, p1 = pad_of("C7", "GND"), P("U1", "1")
T("GND", [g, (g[0], g[1] - 1.2), (p1[0], g[1] - 1.5), p1], W)
# магистраль +3V3 по нижнему слою (под модулем): к подтяжкам EN, I2C и к INA228
YT = 127.5
XV3 = 109.6
V("+3V3", XV3, vo[1])
B("+3V3", [(XV3, vo[1]), (XV3, YT), (142.125, YT)], WP)
r7 = pad_of("R7", "+3V3")
V("+3V3", r7[0], r7[1] + 1.25)
T("+3V3", [r7, (r7[0], r7[1] + 1.25)], W)
B("+3V3", [(r7[0], r7[1] + 1.25), (r7[0], YT)], W)

# --- EN: RC 10k / 1uF
p3 = P("U1", "3")
YEN = 132.6
T("EN", [p3, (p3[0], YEN), (pad_of("R7", "EN")[0], YEN), pad_of("R7", "EN")], W)
T("EN", [(pad_of("C8", "EN")[0], YEN), pad_of("C8", "EN")], W)
g = pad_of("C8", "GND")
T("GND", [g, (g[0], g[1] + 1.25)], W)
V("GND", g[0], g[1] + 1.25)

# --- INA228: адрес 0x40 (A0 = A1 = GND) - via под корпусом
a1, a0 = P("U2", "1"), P("U2", "2")
T("GND", [a1, (a1[0] + 1.1, a1[1]), (a0[0] + 1.1, a0[1]), a0], W)
T("GND", [(a1[0] + 1.1, (a1[1] + a0[1]) / 2), (a1[0] + 1.7, (a1[1] + a0[1]) / 2)], W)
V("GND", a1[0] + 1.7, (a1[1] + a0[1]) / 2, 0.5, 0.25)
# GND вывод 7 -> C3, VS вывод 6 -> C3 -> via в магистраль
g7, vs = P("U2", "7"), P("U2", "6")
c3g, c3v = pad_of("C3", "GND"), pad_of("C3", "+3V3")
T("GND", [g7, (g7[0] + 1.2, g7[1]), (g7[0] + 1.2, c3g[1] - 0.5), c3g], W)
T("GND", [c3g, (c3g[0] + 1.2, c3g[1])], W)
V("GND", c3g[0] + 1.2, c3g[1])
T("+3V3", [vs, (vs[0], c3v[1]), c3v, (c3v[0], YT - 0.8)], W)
V("+3V3", c3v[0], YT - 0.8)
B("+3V3", [(c3v[0], YT - 0.8), (c3v[0], YT)], WP)

# --- I2C и ALERT к правому ряду модуля
al, sda, scl = P("U2", "3"), P("U2", "4"), P("U2", "5")
pa, pd, pc = P("U1", "23"), P("U1", "21"), P("U1", "20")
T("ALERT", [al, (136.2, al[1]), (136.2, pa[1]), pa], W)
T("SDA", [sda, (135.4, sda[1]), (134.3, pd[1]), pd], W)
T("SCL", [scl, (135.0, scl[1]), (134.6, pc[1]), pc], W)
r5 = pad_of("R5", "+3V3")
T("+3V3", [r5, (r5[0] + 1.3, r5[1])], W)
V("+3V3", r5[0] + 1.3, r5[1])
B("+3V3", [(r5[0] + 1.3, r5[1]), (r5[0] + 1.3, YT)], W)
r4 = pad_of("R4", "+3V3")
T("+3V3", [r4, (r4[0], r4[1] + 1.35)], W)
V("+3V3", r4[0], r4[1] + 1.35)
B("+3V3", [(r4[0], r4[1] + 1.35), (r4[0], YT)], W)

# --- вход измерения: Kelvin-пара от клеммы через RC-фильтр
inp, inn = P("U2", "10"), P("U2", "9")
r1i, r2i = pad_of("R1", "INP"), pad_of("R2", "INN")
c1p, c1n = pad_of("C1", "INP"), pad_of("C1", "INN")
T("INP", [r1i, (inp[0] + 1.3, r1i[1]), (inp[0] + 1.3, inp[1]), inp], W)
T("INP", [(c1p[0], r1i[1]), c1p], W)
T("INN", [r2i, (c1n[0], r2i[1]), (c1n[0], inn[1]), inn], W)
j1, j2 = P("J2", "1"), P("J2", "2")
r1s, r2s = pad_of("R1", "SNS_P"), pad_of("R2", "SNS_N")
T("SNS_P", [j1, (152.0, j1[1]), (149.0, j1[1] + 3.0), (149.0, r1s[1]), r1s], W)
T("SNS_N", [j2, (152.5, j2[1]), (150.2, r2s[1]), r2s], W)
d1p, d1n = pad_of("D1", "SNS_P"), pad_of("D1", "SNS_N")
T("SNS_P", [(d1p[0], j1[1]), d1p], W)
T("SNS_N", [(d1n[0], j2[1]), d1n], W)

# --- напряжение аккумулятора: BAT+ -> 10k -> TVS + 100nF -> VBUS INA228
j4 = P("J2", "4")
r3b, r3s = pad_of("R3", "VBAT"), pad_of("R3", "VBUS_S")
vb = P("U2", "8")
T("VBAT", [j4, r3b], WP)
T("VBUS_S", [r3s, (150.0, r3s[1]), (150.0, vb[1]), vb], W)
T("VBUS_S", [pad_of("D2", "VBUS_S"), (pad_of("D2", "VBUS_S")[0], r3s[1])], W)
g = pad_of("D2", "GND")
T("GND", [g, (g[0], g[1] + 1.4)], W)
V("GND", g[0], g[1] + 1.4)
g = pad_of("C2", "GND")
T("GND", [g, (g[0], g[1] + 1.3)], W)
V("GND", g[0], g[1] + 1.3)

# --- кнопки (сигнал на нижние пады, земля - верхние) и светодиод
for ref in ("SW1", "SW2", "SW3"):
    fp = b.fps[ref]
    cx = tomm(fp.GetPosition().x)
    sig = PARTS[ref][3]["2"]
    pads2 = sorted(tomm(p_.GetPosition().x) for p_ in fp.Pads() if p_.GetNumber() == "2")
    pads1 = sorted(tomm(p_.GetPosition().x) for p_ in fp.Pads() if p_.GetNumber() == "1")
    y2 = tomm([p_ for p_ in fp.Pads() if p_.GetNumber() == "2"][0].GetPosition().y)
    y1 = tomm([p_ for p_ in fp.Pads() if p_.GetNumber() == "1"][0].GetPosition().y)
    T(sig, [(pads2[0], y2), (pads2[1], y2)], W)
    T("GND", [(pads1[0], y1), (pads1[1], y1)], W)
    T("GND", [(cx, y1), (cx, y1 - 1.5)], W)
    V("GND", cx, y1 - 1.5)
sw1y = 107.85
m1 = P("U1", "34")
T("MARK1", [m1, (m1[0], sw1y)], W)
m2 = P("U1", "31")
T("MARK2", [m2, (m2[0], 109.6), (119.9, 108.6), (119.9, sw1y)], W)
bt = P("U1", "27")
T("BOOT", [bt, (bt[0], 110.6), (130.9, 110.6), (130.9, sw1y)], W)
led = P("U1", "35")
r8l = pad_of("R8", "LED")
T("LED", [led, (led[0], 111.4), r8l], W)
T("LED_A", [pad_of("R8", "LED_A"), pad_of("D3", "LED_A")], W)
dk, p40 = pad_of("D3", "GND"), P("U1", "40")
T("GND", [dk, (p40[0], dk[1] + 0.6), p40], W)

# -------------------------------------------------- контур, полигоны, шелк
b.edge_rect(X0 + BW / 2, Y0 + BH / 2, BW, BH, 3.0)
b.zone("GND", FCU, X0 + BW / 2, Y0 + BH / 2, BW - 0.6, BH - 0.6)
b.zone("GND", BCU, X0 + BW / 2, Y0 + BH / 2, BW - 0.6, BH - 0.6)

SZ, TH = 0.8, 0.15
# подписи клеммы - в полосе между падами и проёмами под провод, свободной от шелка корпуса
for i, lbl in enumerate(("S+", "S-", "GND", "BAT")):
    x, y = P("J2", str(i + 1))
    b.text(lbl, x + 3.8, y, size=SZ, thick=TH)
for ref, lbl in (("SW1", "MARK1"), ("SW2", "MARK2"), ("SW3", "BOOT")):
    fp = b.fps[ref]
    b.text(lbl, tomm(fp.GetPosition().x), 101.4, size=SZ, thick=TH)
b.text("DRAIN WATCHER", 150.0, 140.0, size=1.5, thick=0.25)
b.text("INA228 / ESP32-S3", 150.0, 142.4, size=SZ, thick=TH)
b.text("USB: powerbank / flashing", 150.0, 144.2, size=SZ, thick=TH)
BS = pcbnew.B_SilkS
for i, line in enumerate(("drain_watcher v1",
                          "SNS+ chassis side, SNS-/GND battery side",
                          "BAT+ via 1A fuse. Bridge shunt to crank!")):
    b.text(line, 146.0, 131.3 + 1.8 * i, layer=BS, size=1.0 if i == 0 else SZ,
           thick=0.2 if i == 0 else TH, mirror=True)

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
REF_FIX = {"J2": (163.0, 108.6, 0), "U1": (118.0, 117.0, 0), "J1": (JX, 148.6, 0)}


def place_ref(fp):
    t = fp.Reference()
    t.SetTextSize(pcbnew.VECTOR2I(mm(SZ), mm(SZ)))
    t.SetTextThickness(mm(TH))
    ref = fp.GetReference()
    if ref.startswith("H"):
        t.SetVisible(False)
        return
    t.SetVisible(True)
    if ref in REF_FIX:
        x, y, a = REF_FIX[ref]
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

# земляные пады USB-C - сплошным соединением
for _p in b.fps["J1"].Pads():
    if _p.GetNetname() == "GND":
        b.pad_zone_connection(_p, pcbnew.ZONE_CONNECTION_FULL)

# (в самом конце: после Remove() SWIG в KiCad 10 теряет типы у прокси-объектов)
# Антенна модуля стоит вровень с краем платы - шелк корпуса за контуром не печатается.
for _g in list(b.fps["U1"].GraphicalItems()):
    if _g.GetLayer() == pcbnew.F_SilkS and tomm(_g.GetBoundingBox().GetLeft()) < X0 + 0.2:
        b.fps["U1"].Remove(_g)

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
                                     # via 0.45/0.3 у USB-C: JLCPCB считает предпочтительным
                                     # минимумом via отверстие + 0.15 мм, то есть пояс 0.075
                                     "min_via_annular_width": 0.075})
json.dump(_d, open(_pro, "w"), indent=2)
print("OK ->", OUT)
