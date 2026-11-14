#!/usr/bin/env python3
"""Генератор проекта KiCad: drain_watcher v3 - логгер тока утечки автомобильного аккумулятора.

ESP32-S3-WROOM-1 + INA228 на одной плате, питание от того же аккумулятора через
понижающий преобразователь 12 -> 5 В, USB-C для прошивки и логов, ряд отверстий под
свободные выводы ESP32, адресный RGB-светодиод, кнопки RESET и BOOT. 2 слоя. Основной
ток по плате не идёт: шунт стоит на силовых шинах, плата снимает с него напряжение
(Kelvin) и напряжение аккумулятора.

    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/gen/build.py hardware
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/gen/route.py hardware/drain_watcher.kicad_pcb

build.py - схема, размещение, шелк и ручная разводка того, что важно провести
определённым образом (вход измерения Kelvin, VBUS INA228, земля адреса). Всё
остальное разводит Freerouting (route.py), потом углы скругляются дугами.
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

# Модуль повёрнут антенной к левому краю (от проводов к шунту): ряд выводов 1-14 смотрит
# вниз (питание, EN, USB), ряд 27-40 - вверх (к ряду отверстий GPIO), ряд 15-26 - вправо,
# к INA228. Под антенной и слева от неё на обоих слоях меди нет (запрет из футпринта,
# x < 106).
MX, MY = 112.75, 122.0
# Узел измерения - тот же, что на модуле INA228 (расставлен вручную в KiCad).
TX, TY = 149.8, 117.6                       # отверстия под провода, шаг 4.6 мм
UX, UY = 135.4, 122.0                       # INA228
# Ряд отверстий GPIO над модулем, шаг 2.54: вывод 1 - сразу правее запретной зоны антенны.
GX, GY = 108.0, 106.6
JX, JY = 128.4, 141.6                       # USB-C, торцом к нижнему краю

X0, X1 = 100.0, 152.0
Y0, Y1 = 104.6, 145.8
BW, BH = X1 - X0, Y1 - Y0

# ------------------------------------------------------------------ детали
R0603 = ("Resistor_SMD", "R_0603_1608Metric")
C0603 = ("Capacitor_SMD", "C_0603_1608Metric")
C0805 = ("Capacitor_SMD", "C_0805_2012Metric")
SOD123 = ("Diode_SMD", "D_SOD-123")
SOD123F = ("Diode_SMD", "D_SOD-123F")
BTN = ("Button_Switch_SMD", "SW_Push_1P1T_XKB_TS-1187A")

# Ряд GPIO: слева направо в том же порядке, что выводы верхнего ряда модуля (39 ... 28),
# справа - питание. Номер вывода модуля -> имя цепи.
HDR = [("39", "IO1"), ("38", "IO2"), ("37", "TXD0"), ("36", "RXD0"), ("35", "IO42"),
       ("34", "IO41"), ("33", "IO40"), ("32", "IO39"), ("31", "IO38"), ("30", "IO37"),
       ("29", "IO36"), ("28", "IO35"), (None, "GND"), (None, "+3V3"), (None, "+5V")]

ESP_NETS = {"1": "GND", "40": "GND", "41": "GND", "2": "+3V3", "3": "EN",
            "13": "USB_DM", "14": "USB_DP",
            "21": "SDA",        # IO13
            "20": "SCL",        # IO12
            "23": "ALERT",      # IO21, подтяжка - внутренняя
            "25": "LED_DIN",    # IO48 - как RGB-светодиод на DevKitC-1
            "27": "BOOT"}       # IO0
for _pn, _n in HDR:
    if _pn:
        ESP_NETS[_pn] = _n

PARTS = {
    "U1": ("RF_Module:ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1-N8R2", ("RF_Module", "ESP32-S3-WROOM-1"),
           ESP_NETS, (MX, MY, 90)),
    "U2": ("Sensor_Energy:INA228", "INA228AIDGSR", ("Package_SO", "MSOP-10_3x3mm_P0.5mm"),
           {"1": "GND", "2": "GND", "3": "ALERT", "4": "SDA", "5": "SCL", "6": "+3V3",
            "7": "GND", "8": "VBUS_S", "9": "INN", "10": "INP"}, (UX, UY, 0)),
    # Провода: 1 - SNS+ (шунт, сторона кузова), 2 - SNS- (шунт, сторона аккумулятора),
    # 3 - GND (отдельный провод на ту же сторону шунта), 4 - BAT+ (через предохранитель 1 А).
    "J2": ("Connector_Generic:Conn_01x04", "WIRES",
           ("Connector_Wire", "SolderWire-0.5sqmm_1x04_P4.6mm_D0.9mm_OD2.1mm"),
           {"1": "SNS_P", "2": "SNS_N", "3": "GND", "4": "VBAT"}, (TX, TY, 270)),
    "J1": ("Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", ("Connector_USB", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
           {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
            "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
            "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP",
            "A7": "USB_DM", "B7": "USB_DM", "SH": "GND"}, (JX, JY, 0)),
    "J3": ("Connector_Generic:Conn_01x15", "GPIO", ("Connector_PinHeader_2.54mm", "PinHeader_1x15_P2.54mm_Vertical"),
           {str(i + 1): n for i, (_, n) in enumerate(HDR)}, (GX, GY, 90)),
    # --- вход измерения (как на модуле INA228)
    "D1": ("Device:D_TVS", "SMF24CA", SOD123F, {"1": "SNS_P", "2": "SNS_N"}, (145.57, 118.86, 270)),
    "R1": ("Device:R", "10R", R0603, {"1": "INP", "2": "SNS_P"}, (UX + 6.6, 118.4, 0)),
    "R2": ("Device:R", "10R", R0603, {"1": "INN", "2": "SNS_N"}, (UX + 6.6, 120.4, 0)),
    "C1": ("Device:C", "100nF", C0603, {"1": "INP", "2": "INN"}, (UX + 4.3, 119.4, 270)),
    "R3": ("Device:R", "10k", ("Resistor_SMD", "R_1206_3216Metric"), {"1": "VBUS_S", "2": "VBAT"}, (143.51, 130.52, 270)),
    "D2": ("Device:D_Zener", "SMF24A", SOD123F, {"1": "VBUS_S", "2": "GND"}, (145.58, 125.42, 270)),
    "C2": ("Device:C", "100nF", C0603, {"1": "VBUS_S", "2": "GND"}, (UX + 6.6, 122.8, 270)),
    "C3": ("Device:C", "100nF", C0603, {"1": "+3V3", "2": "GND"}, (UX + 2.9, 125.3, 0)),
    "R4": ("Device:R", "4.7k", R0603, {"1": "SCL", "2": "+3V3"}, (128.5, 124.75, 270)),
    "R5": ("Device:R", "4.7k", R0603, {"1": "SDA", "2": "+3V3"}, (129.7, 120.55, 90)),
    # --- питание от аккумулятора: BAT+ -> диод от переполюсовки -> TVS + 10 мкФ ->
    # AP63205 (5 В, 2 А, вход 3.8...32 В) -> дроссель -> 2 x 22 мкФ -> диод "ИЛИ" -> +5V
    "D4": ("Device:D_Schottky", "B5819W", SOD123, {"1": "VIN", "2": "VBAT"}, (147.4, 135.8, 90)),
    "D5": ("Device:D_Zener", "SMF24A", SOD123F, {"1": "VIN", "2": "GND"}, (150.4, 140.0, 270)),
    "C10": ("Device:C", "10uF", C0805, {"1": "VIN", "2": "GND"}, (147.4, 140.6, 90)),
    "U3": ("Regulator_Switching:AP63205WU", "AP63205WU-7", ("Package_TO_SOT_SMD", "TSOT-23-6"),
           {"1": "+5V_B", "2": "VIN", "3": "VIN", "4": "GND", "5": "SW", "6": "BST"}, (143.3, 138.4, 180)),
    "C12": ("Device:C", "100nF", C0603, {"1": "BST", "2": "SW"}, (142.2, 141.6, 0)),
    "L1": ("Device:L", "4.7uH", ("Inductor_SMD", "L_Sunlord_SWPA4030S"), {"1": "+5V_B", "2": "SW"}, (137.5, 138.0, 90)),
    "C13": ("Device:C", "22uF", C0805, {"1": "+5V_B", "2": "GND"}, (136.0, 143.6, 0)),
    "C14": ("Device:C", "22uF", C0805, {"1": "+5V_B", "2": "GND"}, (139.6, 143.6, 0)),
    "D6": ("Device:D_Schottky", "B5819W", SOD123, {"1": "+5V", "2": "+5V_B"}, (144.6, 143.6, 0)),
    # USB - через свой диод "ИЛИ": от компьютера и от аккумулятора плата питается
    # одинаково, источники друг в друга не текут
    "D7": ("Device:D_Schottky", "B5819W", SOD123, {"1": "+5V", "2": "VBUS"}, (128.4, 134.0, 0)),
    "R9": ("Device:R", "5.1k", R0603, {"1": "CC1", "2": "GND"}, (124.6, 134.6, 90)),
    "R10": ("Device:R", "5.1k", R0603, {"1": "CC2", "2": "GND"}, (132.2, 134.6, 90)),
    # +5V -> TLV75733 (3.3 В, 1 А, падение ~0.3 В) -> +3V3
    "U4": ("Regulator_Linear:TLV75733PDBV", "TLV75733PDBVR", ("Package_TO_SOT_SMD", "SOT-23-5"),
           {"1": "+5V", "2": "GND", "3": "+5V", "5": "+3V3"}, (134.5, 131.0, 0)),
    "C15": ("Device:C", "10uF", C0805, {"1": "+5V", "2": "GND"}, (131.0, 130.5, 90)),
    "C16": ("Device:C", "10uF", C0805, {"1": "+3V3", "2": "GND"}, (138.0, 131.0, 90)),
    # --- ESP32: развязка у вывода питания, RC на EN, кнопки
    "C7": ("Device:C", "100nF", C0603, {"1": "+3V3", "2": "GND"}, (108.0, 133.5, 90)),
    "C8": ("Device:C", "1uF", C0603, {"1": "EN", "2": "GND"}, (110.2, 133.5, 90)),
    "R7": ("Device:R", "10k", R0603, {"1": "EN", "2": "+3V3"}, (112.4, 133.5, 90)),
    "SW2": ("Switch:SW_Push", "RESET", BTN, {"1": "GND", "2": "EN"}, (110.8, 139.4, 0)),
    "SW1": ("Switch:SW_Push", "BOOT", BTN, {"1": "GND", "2": "BOOT"}, (119.0, 139.4, 0)),
    # --- адресный RGB-светодиод (питание +5V, данные 3.3 В с IO48)
    "D3": ("LED:WS2812B-2020", "WS2812B-2020", ("LED_SMD", "LED_WS2812B-2020_PLCC4_2.0x2.0mm"),
           {"2": "GND", "3": "LED_DIN", "4": "+5V"}, (128.6, 115.2, 0)),
    "C9": ("Device:C", "100nF", C0603, {"1": "+5V", "2": "GND"}, (128.6, 117.9, 0)),
}

b = Builder(layers=2)
for ref, (lid, val, (fl, fn), nets, (x, y, r)) in PARTS.items():
    b.place(ref, fl, fn, x, y, r, value=val)

# J2 и J3 - только отверстия: провода и гребёнку 2.54 мм впаивают по месту, а не на
# заводе. 3D-модели нет, в BOM и в файл установки (CPL) они не попадают.
NOPART = ("J2", "J3")
for _r in NOPART:
    _f = b.fps[_r]
    _f.Models().clear()
    _f.SetAttributes(_f.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)

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
d = kigen.Design(NAME, "drain_watcher v3 - ESP32-S3 + INA228, %.0fx%.0f mm, 2 layers" % (BW, BH), paper="A3")
d.prepare()
SCHAT = {"U1": (80, 110), "U2": (230, 80), "J1": (80, 230), "J2": (330, 80), "J3": (30, 70),
         "U3": (230, 200), "U4": (330, 200)}
small = [r for r in PARTS if r not in SCHAT]
for ref, (lid, val, (fl, fn), nets, _) in PARTS.items():
    at = SCHAT.get(ref)
    if at is None:
        i = small.index(ref)
        at = (160 + 25 * (i % 10), 140 + 25 * (i // 10))
    _pt = kigen.Part(ref, lid, val, "%s:%s" % (fl, fn), nets, at=at)
    if ref in NOPART:
        _pt.in_bom = False                  # только отверстия - деталью в BOM не считаются
    d.add(_pt)
# Источники, которые ERC не видит сам: разъёмы и диоды "ИЛИ" - пассивные выводы
for i, n in enumerate(["GND", "VBAT", "VIN", "VBUS", "+5V", "+5V_B"]):
    d.add(kigen.Part("#FLG%d" % i, "power:PWR_FLAG", "PWR_FLAG", "", {"1": n}, at=(160 + 25 * i, 270)))

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

# ESP32: проверка, что номера выводов модуля - те GPIO, что задуманы
_sym = {p.number: p.name for p in kigen.get_symbol("RF_Module:ESP32-S3-WROOM-1").pins}
for _pn, _want in (("21", "IO13"), ("20", "IO12"), ("23", "IO21"), ("25", "IO48"), ("27", "IO0"),
                   ("13", "USB_D-"), ("14", "USB_D+"), ("39", "IO1"), ("28", "IO35"), ("35", "IO42")):
    assert _sym[_pn] == _want or _want in _sym[_pn], (_pn, _sym[_pn], _want)

# ================================================================= разводка вручную
# Здесь - только то, что должно идти определённым путём. Остальное - route.py.
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


# --- INA228: адрес 0x40 (A0 = A1 = GND), via над микросхемой
a1, a0 = P("U2", "1"), P("U2", "2")
XAG = a1[0] - 0.55
YAG = a1[1] - 1.4
T("GND", [a0, (XAG, a0[1]), (XAG, YAG)], W)
T("GND", [a1, (XAG, a1[1])], W)
V("GND", XAG, YAG)
# GND вывод 7 -> C3, VS вывод 6 -> C3 (+3V3 к C3 подводит роутер)
g7, vs = P("U2", "7"), P("U2", "6")
c3g, c3v = pad_of("C3", "GND"), pad_of("C3", "+3V3")
T("GND", [g7, (g7[0] + 1.2, g7[1]), (g7[0] + 1.2, c3g[1] - 0.5), c3g], W)
T("GND", [c3g, (c3g[0] + 1.2, c3g[1])], W)
V("GND", c3g[0] + 1.2, c3g[1])
T("+3V3", [vs, (vs[0], c3v[1]), c3v], W)

# --- вход измерения: Kelvin-пара от проводов через RC-фильтр
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
XVS = r3s[0]
T("VBUS_S", [r3s, (XVS, r3s[1]), (XVS, vb[1]), vb], W)
d2v = pad_of("D2", "VBUS_S")
T("VBUS_S", [d2v, (XVS, d2v[1])], W)
g = pad_of("D2", "GND")
T("GND", [g, (g[0] + 1.2, g[1] - 0.8)], W)
V("GND", g[0] + 1.2, g[1] - 0.8)
g = pad_of("C2", "GND")
T("GND", [g, (g[0], g[1] + 1.3)], W)
V("GND", g[0], g[1] + 1.3)

# BAT+ -> диод D4: под 45 от отверстия провода к аноду
d4a = pad_of("D4", "VBAT")
T("VBAT", [j4, (j4[0] - (d4a[1] - j4[1]), d4a[1]), d4a], WP)

# Земля мелких падов, к которым заливка не подходит с двух сторон: светодиод - через
# пад GND его конденсатора на via; вывод 1 модуля, C7 и C8 - общей перемычкой на via
# сразу правее запретной зоны антенны.
d3g, c9g = pad_of("D3", "GND"), pad_of("C9", "GND")
YLG = d3g[1] + 0.8
T("GND", [d3g, (d3g[0], YLG), (c9g[0], YLG), c9g], W)
T("GND", [c9g, (c9g[0] + 1.2, c9g[1])], W)
V("GND", c9g[0] + 1.2, c9g[1])
u1g, c7g, c8g = P("U1", "1"), pad_of("C7", "GND"), pad_of("C8", "GND")
T("GND", [u1g, (u1g[0], c7g[1] - 0.6), (c7g[0], c7g[1] - 0.6), c7g], W)
T("GND", [c7g, c8g], W)
T("GND", [c7g, (106.75, c7g[1])], W)
V("GND", 106.75, c7g[1])

# Земля силовой части преобразователя: у каждого пада GND - своё via на нижний слой
# (сплошная земля), иначе выходные конденсаторы остаются на острове верхней заливки.
for _r, _dx, _dy in (("C13", 0.0, 1.45), ("C14", 0.0, 1.45)):
    g = pad_of(_r, "GND")
    T("GND", [g, (g[0] + _dx, g[1] + _dy)], WP)
    V("GND", g[0] + _dx, g[1] + _dy)
g = P("U3", "4")
T("GND", [g, (g[0] - 0.75, g[1] - 0.95)], WP)
V("GND", g[0] - 0.75, g[1] - 0.95)
# подтяжки CC у USB-C - тоже через via
for _r, _dx in (("R9", -1.3), ("R10", 1.3)):
    g = pad_of(_r, "GND")
    T("GND", [g, (g[0] + _dx, g[1])], W)
    V("GND", g[0] + _dx, g[1])
c10g, d5g = pad_of("C10", "GND"), pad_of("D5", "GND")
XG5 = 148.9
T("GND", [c10g, (XG5, c10g[1]), (XG5, d5g[1]), d5g], WP)
V("GND", XG5, c10g[1])

# Всё, что разведено здесь, роутеру трогать нельзя
for _t in b.b.GetTracks():
    _t.SetLocked(True)

# -------------------------------------------------- контур, полигоны, шелк
b.edge_rect(X0 + BW / 2, Y0 + BH / 2, BW, BH, 1.0)
for _ly in (FCU, BCU):
    # куски заливки, не связанные с землёй, выбрасываются
    b.zone("GND", _ly, X0 + BW / 2, Y0 + BH / 2, BW - 0.6, BH - 0.6).SetIslandRemovalMode(
        pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)

SZ, TH = 0.8, 0.15
BS = pcbnew.B_SilkS
# Подписи проводов - повёрнуты на 90, между диодами и отверстиями, с обеих сторон.
for i, lbl in enumerate(("SNS+", "SNS-", "GND", "BAT+")):
    x, y = P("J2", str(i + 1))
    # BAT+ чуть выше и левее - у R3 (выставлено вручную на модуле INA228)
    dx, dy = (-2.28, -0.44) if lbl == "BAT+" else (-2.1, 0.0)
    b.text(lbl, x + dx, y + dy, size=SZ, thick=TH, rot=90)
    b.text(lbl, x + dx, y + dy, layer=BS, size=0.9, thick=0.18, rot=90, mirror=True)
# Подписи ряда GPIO - под отверстиями, вертикально (на шаг 2.54 горизонтально не
# влезают), с обеих сторон: сверху - поверх дорожек веером, это допустимо.
for i, (_, n) in enumerate(HDR):
    x, y = P("J3", str(i + 1))
    lbl = {"TXD0": "TX", "RXD0": "RX", "+3V3": "3V3", "+5V": "5V"}.get(n, n)
    for _ly, _mr in ((pcbnew.F_SilkS, False), (BS, True)):
        _t = b.text(lbl, x, y, layer=_ly, size=0.8, thick=0.15, rot=90, mirror=_mr)
        _top = tomm(_t.GetBoundingBox().GetTop())      # верх надписи - сразу под отверстием
        _t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y + (y - _top) + 1.15)))
_j3silk = [g for g in b.fps["J3"].GraphicalItems() if g.GetLayer() == pcbnew.F_SilkS]
for _ref, _lbl, _dx in (("SW2", "RST", 0.0), ("SW1", "BOOT", 0.0)):
    _q = b.fps[_ref].GetPosition()
    b.text(_lbl, tomm(_q.x) + _dx, tomm(_q.y) + 4.1, size=1.0, thick=0.2)


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
    anchor место, где ни одна надпись не ложится на пад или отверстие.
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
            if bx[0] < X0 + 0.6 or bx[2] > X1 - 0.6 or bx[1] < Y0 + 0.6 or bx[3] > Y1 - 0.6 \
                    or any(_hit(bx, o, 0.2) for o in obs):
                ok = False
                break
        if ok:
            return (cx, cy)
    print("  на обратной стороне нет места для группы надписей (%s)" % items[0][0])
    return None


def _size(txt, sz, th, a=0):
    t = b.text(txt, 0, 0, layer=BS, size=sz, thick=th, rot=a, mirror=True)
    bb = kicadenv.textbox(t)
    w, h = tomm(bb.GetWidth()), tomm(bb.GetHeight())
    b.b.Remove(t)
    return w, h


def stack(lines, anchor):
    its, y = [], 0.0
    for t_, sz_, th_ in lines:
        h_ = _size(t_, sz_, th_)[1]
        its.append((t_, 0.0, y + h_ / 2, 0, sz_, th_))
        y += h_ + 0.25
    return back_group(its, anchor)


# Обратная сторона: бренд, шунт, памятка и легенда номиналов - столбцами, место ищется
# по свободной от падов и отверстий площади.
LSZ, LTH = 1.0, 0.18
stack([("ASTechLab", 2.0, 0.5), ("DRAIN WATCHER v3", 1.5, 0.375)], (113.0, 118.0))
stack([("4 terminal shunt", 1.0, 0.25), ("2.5 mOhm 30A 75mV", 1.0, 0.25),
       ("BAT+ via 1A fuse", 1.0, 0.25), ("Never crank through shunt!", 1.0, 0.25)], (113.0, 127.0))
_legend = sorted(LEGEND, key=lambda l: (not l.startswith("U"), _key(l.split(":")[0].split(",")[0])))
# первый столбец - высокий, по центру платы; остаток - двумя короткими блоками в нижней
# полосе (на обороте под кнопками и под преобразователем свободно)
_n1 = 10
_rest = _legend[_n1:]
_n2 = (len(_rest) + 1) // 2
stack([(l, LSZ, LTH) for l in _legend[:_n1]], (132.0, 122.0))
stack([(l, LSZ, LTH) for l in _rest[:_n2]], (143.0, 139.0))
stack([(l, LSZ, LTH) for l in _rest[_n2:]], (112.0, 140.5))
print("легенда номиналов: %d строк" % len(LEGEND))


# Обозначения деталей: шрифт по нормам JLCPCB (0.8 / 0.15). Место для каждого ищется
# перебором вокруг детали: занятыми считаются пады, корпуса (courtyard) других деталей,
# уже поставленные надписи и полоса у края платы.
def _box(item):
    bb = kicadenv.textbox(item) if item.GetClass() in ("PCB_TEXT", "PCB_FIELD") else item.GetBoundingBox()
    return (tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom()))


OBST = []
for _fp in b.b.GetFootprints():
    for _p in _fp.Pads():
        OBST.append(("pad", _box(_p)))
    if _fp.GetReference() == "U1":
        # у модуля курьтъярд - вместе с зоной антенны на пол-платы; занят только корпус
        _bb = _fp.GetBoundingBox(False)
        OBST.append(("crtyd", (MX - 12.75, MY - 9.0, MX + 12.75, MY + 9.0)))
        continue
    _cy = _fp.GetCourtyard(pcbnew.F_CrtYd)
    if _cy.OutlineCount():
        _bb = _cy.BBox()
        OBST.append(("crtyd", (tomm(_bb.GetLeft()), tomm(_bb.GetTop()),
                               tomm(_bb.GetRight()), tomm(_bb.GetBottom()))))
for _d in b.b.GetDrawings():
    if _d.GetClass() == "PCB_TEXT" and _d.GetLayer() == pcbnew.F_SilkS:
        OBST.append(("text", _box(_d)))
for _t in b.b.GetTracks():
    if _t.GetClass() == "PCB_VIA":
        OBST.append(("via", _box(_t)))
# Положения обозначений, выставленные вручную в KiCad (x, y, угол[, размер, толщина])
REF_FIX = {"C1": (137.78, 119.25, 0), "C2": (140.39, 123.22, 0), "C3": (135.175, 125.3, 0),
           "D1": (145.56, 121.97, 0, 1.0, 0.25), "D2": (145.65, 128.55, 0, 1.0, 0.25),
           "R1": (142.08, 116.76, 0), "R2": (140.26, 121.71, 0), "R3": (145.76, 130.6, 0, 1.0, 0.25),
           "R4": (130.11, 124.77, 0), "R5": (131.42, 120.68, 0),
           "U2": (135.4, 119.305, 0), "U1": (119.5, 128.6, 0, 1.5, 0.25),
           "C10": (149.8, 143.6, 0), "SW1": (119.0, 135.9, 0), "C12": (144.0, 141.45, 90), "D6": (147.6, 143.6, 90), "D5": (150.5, 136.9, 0), "C13": (136.0, 141.75, 0), "C14": (139.6, 141.75, 0)}


def place_ref(fp):
    t = fp.Reference()
    t.SetTextSize(pcbnew.VECTOR2I(mm(SZ), mm(SZ)))
    t.SetTextThickness(mm(TH))
    ref = fp.GetReference()
    if ref in ("J2", "J3"):                 # у проводов и GPIO - свои подписи
        t.SetVisible(False)
        return
    t.SetVisible(True)
    if ref in REF_FIX:
        x, y, a = REF_FIX[ref][:3]
        if len(REF_FIX[ref]) > 3:
            t.SetTextSize(pcbnew.VECTOR2I(mm(REF_FIX[ref][3]), mm(REF_FIX[ref][3])))
        if len(REF_FIX[ref]) > 4:
            t.SetTextThickness(mm(REF_FIX[ref][4]))
        t.SetTextAngleDegrees(a)
        t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        OBST.append(("text", _box(t)))
        return
    cy = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
    l, tp, r, bt = tomm(cy.GetLeft()), tomm(cy.GetTop()), tomm(cy.GetRight()), tomm(cy.GetBottom())
    cx, cyy = (l + r) / 2, (tp + bt) / 2
    cands = []
    for d_ in (0.0, 0.4, 0.8, 1.2, 1.8, 2.5):
        cands += [(cx, tp - 0.5 - d_, 0), (cx, bt + 0.5 + d_, 0), (l - 0.6 - d_, cyy, 90),
                  (r + 0.6 + d_, cyy, 90), (l - 1.6 - d_, cyy, 0), (r + 1.6 + d_, cyy, 0),
                  (l - 1.2 - d_, tp - 0.3, 0), (r + 1.2 + d_, tp - 0.3, 0),
                  (l - 1.2 - d_, bt + 0.3, 0), (r + 1.2 + d_, bt + 0.3, 0)]
    for strict in (True, False):
        for x, y, a in cands:
            t.SetTextAngleDegrees(a)
            t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            bx = _box(t)
            if bx[0] < X0 + 0.5 or bx[2] > X1 - 0.5 or bx[1] < Y0 + 0.5 or bx[3] > Y1 - 0.5:
                continue
            if bx[0] < 106.0:               # слева - антенна, шелк туда не ставим
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
# рамка гребёнки J3 на лицевой стороне наезжает на подписи - оставляем только квадратный
# пад 1 как метку
for _g in _j3silk:
    b.fps["J3"].Remove(_g)
for _r in NOPART:
    for _g in list(b.fps[_r].GraphicalItems()):
        if _g.GetClass() == "PCB_TEXT" and _g.GetLayer() == pcbnew.F_Fab:
            b.fps[_r].Remove(_g)

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

b.finish(os.path.join(OUT, NAME + ".kicad_pcb"), fill=False)

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
