#!/usr/bin/env python3
"""Автотрассировка платы через Freerouting и скругление углов дугами.

    "C:/Program Files/KiCad/10.0/bin/python.exe" gen/route.py drain_watcher.kicad_pcb [--reroute]

1. Плата (после build.py, с ручной разводкой - она заблокирована) -> Specctra DSN.
   В DSN дописываются классы цепей (ширина питания) и режим углов 45 градусов.
2. Freerouting разводит остальное -> .ses. Результат кэшируется: если DSN не
   изменился, берётся прошлый .ses (он лежит в репозитории), роутер не запускается.
   --reroute - развести заново.
3. .ses импортируется в плату, каждый излом дорожки заменяется дугой (радиус до
   R_FILLET), затем DRC: дуги, из-за которых нарушен зазор, откатываются обратно
   в излом.

Freerouting: переменные FREEROUTING_JAR и JAVA, по умолчанию - C:/Users/<you>/tools.
"""
import glob, hashlib, json, math, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv
kicadenv.quiet()
import pcbnew
from pcbhelp import mm, tomm, fill_zones

PCB = os.path.abspath(sys.argv[1])
REROUTE = "--reroute" in sys.argv
BASE = os.path.splitext(PCB)[0]
DSN, SES, KEY = BASE + ".dsn", BASE + ".ses", BASE + ".ses.key"
R_FILLET = 1.0                              # мм, наибольший радиус скругления

# Классы цепей для роутера: ширина дорожки, мм. Остальное - 0.2.
CLASSES = {
    "pwr": (0.5, ["VBAT", "VIN", "SW", "+5V_B"]),
    "pwr4": (0.4, ["+5V", "VBUS", "+3V3", "GND"]),
    # пады USB-C - 0.3 мм с шагом 0.5: дорожка 0.2 между ними не проходит, и роутер
    # сам сужал её до 0.1 (меньше нормы). Сразу 0.15 - в норме JLCPCB.
    "usb": (0.15, ["USB_DP", "USB_DM", "CC1", "CC2"]),
}
TOOLS = os.path.join(os.path.expanduser("~"), "tools")
JAR = os.environ.get("FREEROUTING_JAR") or os.path.join(TOOLS, "freerouting", "freerouting-2.5.0.jar")
JAVA = os.environ.get("JAVA") or (glob.glob(os.path.join(TOOLS, "jre", "*", "bin", "java.exe")) +
                                  glob.glob(os.path.join(TOOLS, "jre", "*", "bin", "java")) + ["java"])[0]


def cli():
    exe = "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
    near = os.path.join(os.path.dirname(os.path.dirname(kicadenv.share_dir())), "bin", exe)
    return near if os.path.exists(near) else exe


# ------------------------------------------------------------------ 1. DSN
def patch_dsn(text):
    """Классы цепей и углы 45 градусов в DSN, который пишет KiCad."""
    m = re.search(r"\(class kicad_default ([^(]*)", text)
    names = m.group(1).split()
    moved = {n for _, (_, ns) in CLASSES.items() for n in ns}
    q = lambda n: '"%s"' % n if re.search(r"[^A-Za-z0-9_]", n) else n
    unq = lambda n: n.strip('"')
    keep = [n for n in names if unq(n) not in moved]
    text = text[:m.start(1)] + " ".join(keep) + "\n      " + text[m.end(1):]
    # блок kicad_default целиком - образец для новых классов
    i = text.index("(class kicad_default")
    depth, j = 0, i
    while True:
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    present = {unq(n) for n in names}
    add = ""
    for cname, (w, nets) in CLASSES.items():
        nets = [n for n in nets if n in present]
        if not nets:
            continue
        add += ('\n    (class %s %s\n      (circuit\n        (use_via "Via[0-1]_600:300_um")\n      )\n'
                '      (rule\n        (width %d)\n        (clearance 200)\n      )\n    )'
                % (cname, " ".join(q(n) for n in nets), round(w * 1000)))
    text = text[:j + 1] + add + text[j + 1:]
    # только 45 градусов: два излома по 45 вместо прямого угла
    text = text.replace("(structure", "(structure\n    (snap_angle fortyfive_degree)", 1)
    return text


def P(v):
    return (tomm(v.x), tomm(v.y))


def fillet_all(board):
    """Каждый излом из двух прямых отрезков (одна цепь, слой и ширина, без via и пада
    в точке излома) -> дуга, касательная к обоим. Возвращает записи для отката."""
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    ends = {}
    for t in tracks:
        for e, pt in (("s", t.GetStart()), ("e", t.GetEnd())):
            k = (pt.x, pt.y, t.GetLayer(), t.GetNetCode())
            ends.setdefault(k, []).append((t, e))
    # точки, где к дорожке примыкает что-то ещё той же цепи (конец другой дорожки,
    # пад, via): дугу нельзя начинать дальше них, иначе примыкание повиснет в воздухе
    taps = {}
    for t in tracks:
        for pt in (t.GetStart(), t.GetEnd()):
            taps.setdefault((t.GetLayer(), t.GetNetCode()), []).append(P(pt))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            for ly in (pcbnew.F_Cu, pcbnew.B_Cu):
                if p.IsOnLayer(ly):
                    taps.setdefault((ly, p.GetNetCode()), []).append(P(p.GetPosition()))
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            for ly in (pcbnew.F_Cu, pcbnew.B_Cu):
                taps.setdefault((ly, t.GetNetCode()), []).append(P(t.GetPosition()))

    def room(c, u, l, key):
        """Сколько можно отрезать от отрезка c -> c + u*l до первого примыкания."""
        best = l
        for q in taps.get(key, ()):
            vx, vy = q[0] - c[0], q[1] - c[1]
            tpar = vx * u[0] + vy * u[1]
            if 1e-3 < tpar < l - 1e-3 and abs(vx * u[1] - vy * u[0]) < 0.01:
                best = min(best, tpar)
        return best

    blocked = []      # центры via и падов: допуск - округление координат в DSN/SES
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            blocked.append(P(t.GetPosition()))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            blocked.append(P(p.GetPosition()))
    # сколько длины каждого отрезка можно забрать под дуги: по половине на каждый конец
    plans = []
    for (x, y, layer, net), lst in ends.items():
        if len(lst) != 2 or any(math.dist((tomm(x), tomm(y)), q) < 0.05 for q in blocked):
            continue
        (t1, e1), (t2, e2) = lst
        if t1.GetWidth() != t2.GetWidth():
            continue
        c = (tomm(x), tomm(y))
        o1 = P(t1.GetEnd() if e1 == "s" else t1.GetStart())
        o2 = P(t2.GetEnd() if e2 == "s" else t2.GetStart())
        l1, l2 = math.dist(c, o1), math.dist(c, o2)
        if l1 < 1e-3 or l2 < 1e-3:
            continue
        u1 = ((o1[0] - c[0]) / l1, (o1[1] - c[1]) / l1)
        u2 = ((o2[0] - c[0]) / l2, (o2[1] - c[1]) / l2)
        cosa = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        alpha = math.acos(cosa)                 # угол между отрезками в изломе
        if alpha > math.radians(179) or alpha < math.radians(20):
            continue
        tan_h = math.tan(alpha / 2)
        key = (layer, net)
        w = tomm(t1.GetWidth())
        dmax = min(0.5 * min(l1, l2), room(c, u1, l1, key) - w, room(c, u2, l2, key) - w) - 0.001
        d = min(R_FILLET / tan_h, dmax)
        r = d * tan_h
        if r < 0.15:
            continue
        p1 = (c[0] + u1[0] * d, c[1] + u1[1] * d)
        p2 = (c[0] + u2[0] * d, c[1] + u2[1] * d)
        bis = (u1[0] + u2[0], u1[1] + u2[1])
        bl = math.hypot(*bis)
        bis = (bis[0] / bl, bis[1] / bl)
        oc = r / math.sin(alpha / 2)
        mid = (c[0] + bis[0] * (oc - r), c[1] + bis[1] * (oc - r))
        plans.append((t1, e1, p1, t2, e2, p2, mid, c, layer, net))
    recs = []
    for t1, e1, p1, t2, e2, p2, mid, c, layer, net in plans:
        for t, e, p in ((t1, e1, p1), (t2, e2, p2)):
            v = pcbnew.VECTOR2I(mm(p[0]), mm(p[1]))
            t.SetStart(v) if e == "s" else t.SetEnd(v)
        a = pcbnew.PCB_ARC(board)
        a.SetStart(pcbnew.VECTOR2I(mm(p1[0]), mm(p1[1])))
        a.SetMid(pcbnew.VECTOR2I(mm(mid[0]), mm(mid[1])))
        a.SetEnd(pcbnew.VECTOR2I(mm(p2[0]), mm(p2[1])))
        a.SetWidth(t1.GetWidth())
        a.SetLayer(layer)
        a.SetNetCode(net)
        a.SetLocked(t1.IsLocked() and t2.IsLocked())
        board.Add(a)
        recs.append({"arc": a.m_Uuid.AsString(), "c": c,
                     "t": [(t1.m_Uuid.AsString(), e1), (t2.m_Uuid.AsString(), e2)]})
    return recs


def drc_bad_items():
    """uuid объектов, у которых DRC нашёл нарушение зазора или пересечение."""
    rpt = BASE + ".route_drc.json"
    subprocess.run([cli(), "pcb", "drc", "--format", "json", "--severity-error", "-o", rpt, PCB],
                   capture_output=True, text=True)
    bad = set()
    for v in json.load(open(rpt, encoding="utf8")).get("violations", []):
        if v.get("type") in ("clearance", "tracks_crossing", "shorting_items", "copper_edge_clearance",
                             "hole_clearance", "solder_mask_bridge"):
            for it in v.get("items", []):
                bad.add(it.get("uuid"))
    os.remove(rpt)
    return bad


def cleanup(board):
    """Хвосты роутера (оптимизатор Freerouting не всегда запускается): via, к которым
    дорожки подходят только с одного слоя, и тупиковые отрезки, ведущие в никуда. Земля
    не трогается (её via сшивают заливки), ручная разводка - тоже (она заблокирована)."""
    # Удаление - только в самом конце: после Remove() SWIG в KiCad 10 теряет типы
    # у прокси-объектов. До того - помечаем и пересчитываем без помеченных.
    items = list(board.GetTracks())
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    kill = set()
    while True:
        tracks = [t for t in items if t.GetClass() != "PCB_VIA" and t.m_Uuid.AsString() not in kill]
        vias = [t for t in items if t.GetClass() == "PCB_VIA" and t.m_Uuid.AsString() not in kill]
        n0 = len(kill)
        for v in vias:
            if v.GetNetname() == "GND" or v.IsLocked() or v.m_Uuid.AsString() in kill:
                continue
            pos, r = v.GetPosition(), v.GetWidth(pcbnew.F_Cu) // 2
            lays = {t.GetLayer() for t in tracks if t.GetNetCode() == v.GetNetCode()
                    and min((t.GetStart() - pos).EuclideanNorm(), (t.GetEnd() - pos).EuclideanNorm()) < r}
            if len(lays) < 2 and not any(p.GetNetCode() == v.GetNetCode() and p.HitTest(pos) for p in pads):
                kill.add(v.m_Uuid.AsString())
        for t in tracks:
            if t.IsLocked() or t.GetNetname() == "GND":
                continue
            me = t.m_Uuid.AsString()
            for pt in (t.GetStart(), t.GetEnd()):
                ok = any(o.m_Uuid.AsString() != me and o.GetNetCode() == t.GetNetCode()
                         and o.GetLayer() == t.GetLayer() and o.HitTest(pt, 1000) for o in tracks) \
                    or any(v.m_Uuid.AsString() not in kill and v.GetNetCode() == t.GetNetCode()
                           and v.HitTest(pt) for v in vias) \
                    or any(p.GetNetCode() == t.GetNetCode() and p.IsOnLayer(t.GetLayer()) and p.HitTest(pt)
                           for p in pads)
                if not ok:
                    kill.add(me)
                    break
        if len(kill) == n0:
            break
    for k in [t for t in items if t.m_Uuid.AsString() in kill]:
        board.Remove(k)
    return len(kill)


def revert(board, recs):
    """Откатить скругления: дуга убирается, отрезки снова сходятся в изломе."""
    byid = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
    gone = []
    for r in recs:
        a = byid.get(r["arc"])
        if a is None:
            continue
        c = pcbnew.VECTOR2I(mm(r["c"][0]), mm(r["c"][1]))
        for u, e in r["t"]:
            t = byid[u]
            t.SetStart(c) if e == "s" else t.SetEnd(c)
        gone.append(a)
    for a in gone:                          # удаление - последним (SWIG в KiCad 10)
        board.Remove(a)


def stage(name, arg=None):
    """Шаг с удалением объектов - в отдельном процессе: после Remove() SWIG в KiCad 10
    теряет типы у всех прокси-объектов процесса, и дальше с платой работать нельзя."""
    cmd = [sys.executable, os.path.abspath(__file__), PCB, "--stage", name] + ([arg] if arg else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = "\n".join(l for l in (r.stdout + r.stderr).splitlines()
                    if not re.search(r"assert|image handler|memory leak", l, re.I))
    if r.returncode != 0:
        raise SystemExit("шаг %s:\n%s" % (name, out[-1500:]))
    if out.strip():
        print(out.strip())


if "--stage" in sys.argv:
    _st = sys.argv[sys.argv.index("--stage") + 1]
    b = pcbnew.LoadBoard(PCB)
    if _st == "cleanup":
        print("убрано хвостов роутера: %d" % cleanup(b))
    elif _st == "revert":
        revert(b, json.load(open(sys.argv[sys.argv.index("--stage") + 2], encoding="utf8")))
    pcbnew.SaveBoard(PCB, b)
    sys.exit(0)


def drc_errors():
    """Ошибки DRC (не предупреждения) плюс несоединённые пады."""
    rpt = BASE + ".route_drc.json"
    subprocess.run([cli(), "pcb", "drc", "--format", "json", "--severity-error", "-o", rpt, PCB],
                   capture_output=True, text=True)
    d = json.load(open(rpt, encoding="utf8"))
    os.remove(rpt)
    kinds = {}
    for v in d.get("violations", []) + d.get("unconnected_items", []):
        kinds[v.get("type")] = kinds.get(v.get("type"), 0) + 1
    if kinds:
        print("   DRC:", ", ".join("%s %d" % kv for kv in sorted(kinds.items())))
    return sum(kinds.values())


def board_key(b):
    """Ключ кэша разводки - по тому, что видит роутер: детали и их места, цепи падов,
    ручные дорожки и via, классы цепей. Сам DSN для этого не годится: порядок деталей
    и номера образов в нём KiCad выдаёт каждый раз другие."""
    rows = []
    for fp in b.GetFootprints():
        q = fp.GetPosition()
        pads = ",".join(sorted("%s=%s" % (p.GetNumber(), p.GetNetname()) for p in fp.Pads()))
        rows.append("fp %s %s %d %d %.1f %s" % (fp.GetReference(), fp.GetFPID().GetLibItemName(),
                                               q.x, q.y, fp.GetOrientationDegrees(), pads))
    for t in b.GetTracks():
        s_, e_ = t.GetStart(), t.GetEnd()
        rows.append("tr %s %s %d %d %d %d %d %d" % (t.GetClass(), t.GetNetname(), t.GetLayer(),
                                                   s_.x, s_.y, e_.x, e_.y, t.GetWidth()))
    rows.append(repr(sorted(CLASSES.items())))
    rows.append(os.path.basename(JAR))
    return hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()


def route_once(reroute):
    """DSN -> Freerouting (или кэш) -> импорт -> чистка хвостов -> дуги."""
    b = pcbnew.LoadBoard(PCB)
    pcbnew.ExportSpecctraDSN(b, DSN)
    dsn = patch_dsn(open(DSN, encoding="utf8").read())
    open(DSN, "w", encoding="utf8").write(dsn)
    key = board_key(b)

    # -------------------------------------------------------------- 2. роутер
    cached = os.path.exists(SES) and os.path.exists(KEY) and open(KEY).read().strip() == key
    if cached and not reroute:
        print("Freerouting: DSN не изменился - берём прошлый", os.path.basename(SES))
    else:
        print("Freerouting:", JAR)
        r = subprocess.run([JAVA, "-jar", JAR, "--gui.enabled=false", "--router.automatic_neckdown=false", "--router.neck_width_um=150", "-de", DSN, "-do", SES,
                            "--router.autorouter.max_passes=200"], capture_output=True, text=True, timeout=1800)
        log = r.stdout + r.stderr
        open(BASE + ".freerouting.log", "w", encoding="utf8").write(log)
        if r.returncode != 0 or not os.path.exists(SES):
            raise SystemExit("Freerouting не отработал:\n" + log[-2000:])
        for ln in log.splitlines():
            if re.search(r"stage completed", ln, re.I):
                print("  ", ln[24:].strip()[:150])
        open(KEY, "w").write(key + "\n")

    # -------------------------------------------------------------- 3. импорт
    if not pcbnew.ImportSpecctraSES(b, SES):
        raise SystemExit("ImportSpecctraSES: ошибка")
    # Freerouting сужает дорожку у узких падов (0.75 ширины класса, у USB-C это 0.11 мм),
    # отключить это из командной строки не выходит. Сужения - до 0.13 мм: это в нормах
    # JLCPCB для двухслойки (от 0.127), а зазор до соседних падов разъёма ещё остаётся
    # (при 0.15 его не хватало на сотую). Если всё же не хватит, DRC забракует попытку.
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK" and not t.IsLocked() and t.GetWidth() < mm(0.13):
            t.SetWidth(mm(0.13))
    pcbnew.SaveBoard(PCB, b)
    stage("cleanup")

    # -------------------------------------------------------------- 4. дуги
    # Ручная разводка заблокирована в build.py, роутер её не трогал - скругляем всё.
    b = pcbnew.LoadBoard(PCB)
    recs = fillet_all(b)
    print("скруглено изломов: %d" % len(recs))
    pcbnew.SaveBoard(PCB, b)
    fill_zones(PCB)
    RECS = BASE + ".fillets.json"
    for _ in range(4):
        bad = drc_bad_items()
        back = [r for r in recs if r["arc"] in bad or any(u in bad for u, _ in r["t"])]
        if not back:
            break
        json.dump(back, open(RECS, "w", encoding="utf8"))
        stage("revert", RECS)
        os.remove(RECS)
        recs = [r for r in recs if r not in back]
        print("  откат скруглений у нарушений зазора: %d" % len(back))
        fill_zones(PCB)
    print("дуг на плате: %d" % len(recs))


# Freerouting от прогона к прогону разводит по-разному, и изредка оставляет то, что
# DRC KiCad не пропускает (сужение дорожки у узких падов, недоведённый провод). Тогда -
# заново с исходной платы, пока не выйдет чисто; удачный .ses кэшируется.
if any(t.GetClass() == "PCB_ARC" for t in pcbnew.LoadBoard(PCB).GetTracks()):
    raise SystemExit("плата уже разведена и скруглена - сначала заново build.py")
PRE = BASE + ".pre_route.kicad_pcb"
shutil.copyfile(PCB, PRE)
ATTEMPTS = 8
for attempt in range(1, ATTEMPTS + 1):
    if attempt > 1:
        shutil.copyfile(PRE, PCB)
    route_once(REROUTE or attempt > 1)
    n = drc_errors()
    if n == 0:
        break
    print("попытка %d: ошибок DRC %d - разводим заново" % (attempt, n))
else:
    raise SystemExit("за %d попыток чисто развести не удалось" % ATTEMPTS)
os.remove(PRE)
print("разводка: DRC чистый (попытка %d)" % attempt)
