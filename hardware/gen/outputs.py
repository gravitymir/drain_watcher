#!/usr/bin/env python3
"""BOM + карта выводов гребёнок из готовой платы."""
import sys, os, csv, json, re
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

kicadenv.quiet()
import pcbnew

path = sys.argv[1]
out = os.path.dirname(path)
name = os.path.splitext(os.path.basename(path))[0]
b = pcbnew.LoadBoard(path)

rows = defaultdict(list)
tht = {}
for fp in b.GetFootprints():
    ref = fp.GetReference()
    if ref.startswith("REF") or not ref:
        continue
    pads = list(fp.Pads())
    if fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM:
        continue        # отверстия под провода и т.п. - деталью не являются
    if not pads or all(p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH for p in pads):
        continue        # крепёжные отверстия: паять нечего, в BOM для сборки не нужны
    fid = "%s:%s" % (fp.GetFPID().GetLibNickname(), fp.GetFPID().GetLibItemName())
    rows[(fp.GetValue(), fid)].append(ref)
    # Выводные детали (гребёнки) в SMT-монтаж не идут - помечаем, чтобы не советовать
    # для них номер LCSC как для устанавливаемой автоматом.
    if all(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in pads):
        tht[fp.GetValue()] = True

# Номера LCSC из списка Basic Parts JLCPCB. Ключ - номинал вместе с футпринтом:
# 100nF в 0402 и в 0603 это разные детали с разными номерами.
LCSC = {
    ("100nF", "C_0603_1608Metric"): "C14663",    # Yageo CC0603KRX7R9BB104, 50 В
    ("1uF", "C_0603_1608Metric"): "C15849",      # Samsung CL10A105KB8NNNC, 50 В
    ("10uF", "C_0805_2012Metric"): "C15850",     # Samsung CL21A106KAYNNNE, 25 В
    ("10k", "R_0603_1608Metric"): "C25804",      # Uniroyal 0603WAF1002T5E, 1%
    ("4.7k", "R_0603_1608Metric"): "C23162",     # Uniroyal 0603WAF4701T5E, 1%
    ("1k", "R_0603_1608Metric"): "C21190",       # Uniroyal 0603WAF1001T5E, 1%
    ("5.1k", "R_0603_1608Metric"): "C23186",     # Uniroyal 0603WAF5101T5E, 1%
    ("10R", "R_0603_1608Metric"): "C22859",      # Uniroyal 0603WAF100JT5E
    ("10k", "R_1206_3216Metric"): "C17902",      # Uniroyal 1206W4F1002T5E, 200 В
    ("22uF", "C_0805_2012Metric"): "C45783",     # Samsung CL21A226MAQNNNE, 25 В
}
ALT = {
    "ESP32-S3-WROOM-1-N8R2": "подойдёт ESP32-S3-WROOM-1-N8 (C2913198); N16R8 - нет: восьмибитная PSRAM занимает IO35-IO37",
    "B5819W": "любой Шоттки 40 В 1 А в SOD-123 (SS14 в SMA не встанет)",
    "ICS-43434": "снят с производства (EOL), склад мал - проверить; иначе не ставить и паять вручную",
}
LCSC_ANY = {
    "ESP32-S3-WROOM-1-N8R2": "C2913204",
    "INA228AIDGSR": "C2887910",
    "AP63205WU-7": "C2071056",
    "TLV75733PDBVR": "C485517",
    "WS2812B-2020": "C965555",
    "B5819W": "C8598",
    "4.7uH": "C57269",      # Sunlord SWPA4030S4R7MT
    "ICS-43434": "C5656610",  # TDK, LGA-6, I2S MEMS
    "USB-C": "C165948",
    "SMF24CA": "C3035829",  # PAKER, двунаправленный, SOD-123FL
    "SMF24A": "C3035828",   # PAKER, однонаправленный, SOD-123FL
    # XKB TS-1187A-B-A-B: корпус 5.1x5.1
    "BOOT": "C318884",
    "RESET": "C318884",
}
with open(os.path.join(out, "BOM.csv"), "w", newline="") as f:
    w = csv.writer(f)
    # Имена колонок - те, что ждёт JLCPCB (Comment / Designator / Footprint /
    # LCSC Part #); свои Qty и примечание идут следом, лишние колонки он игнорирует.
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Qty", "Note"])
    # Пассивку берут по номиналу и типоразмеру, а активной детали нужен конкретный
    # номер - советовать для неё "подобрать по номиналу" бессмысленно.
    passive = re.compile(r"^[\d.]+\s*(?:[pnuµmk]?[FRH]|R|k|M|Ohm)\b|^0R$|^LED$", re.I)
    # Одинаковые детали сводим в одну строку по номеру LCSC. У кнопок "номинал" -
    # это функция (RESET / BOOT0), а деталь одна: две строки на один номер
    # JLCPCB помечает как "multiple lines matched to the same part".
    merged = defaultdict(list)
    for (val, fid), refs in rows.items():
        code = LCSC.get((val, fid.split(":")[-1])) or LCSC_ANY.get(val, "")
        merged[(code, fid) if code else (val, fid)].append((val, refs))
    for (_k, fid), group in sorted(merged.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        val0 = group[0][0]
        val = "/".join(sorted({v for v, _ in group}))
        refs = [r for _, rr in group for r in rr]
        code = LCSC.get((val0, fid.split(":")[-1])) or LCSC_ANY.get(val0, "")
        if code:
            note = "проверить наличие на складе"
            if val0 in ALT:
                note += "; " + ALT[val0]
        elif tht.get(val0):
            note = "выводная: в SMT-монтаж не идёт, паяется отдельно"
            if val0 == "I2C":
                note += "; гребёнка 1x5 шаг 2.54 мм или провода к контроллеру"
            if val0 == "SHUNT/BAT":
                note += "; клемма 5.08 мм на 4 контакта (KF128 / DG128 / Phoenix MKDS 1,5/4-5,08)"
        elif passive.match(val):
            note = "подобрать из JLCPCB Basic Parts по номиналу/типоразмеру"
        else:
            note = "уточнить номер LCSC под конкретную деталь"
        w.writerow([val, ",".join(sorted(refs)), fid, code, len(refs), note])

geom = os.path.join(out, "_geom.json")
if os.path.exists(geom):
    g = json.load(open(geom))
    netof = g.get("netof", {})
    with open(os.path.join(out, "PINOUT.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Header", "HeaderPin", "MCU_Pin", "Signal"])
        for k, mn in sorted(g["hdrmap"].items(), key=lambda kv: (kv[0].split(".")[0], int(kv[0].split(".")[1]))):
            ref, hn = k.split(".")
            w.writerow([ref, hn, mn, netof.get(str(mn), "")])
print("BOM.csv / PINOUT.csv ->", out)
