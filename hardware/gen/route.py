#!/usr/bin/env python3
"""Автотрассировка платы kroute и скругление углов дугами, без KiCad.

    PYTHONPATH=<kroute>/python python gen/route.py drain_watcher.kicad_pcb [--reroute]

1. kroute route разводит всё, что не развела build.py (ручная разводка там
   заблокирована и остаётся как есть). Ширины цепей - CLASSES (правила [[net]]
   во временном kroute.toml), углы 45 градусов.
2. Новая медь кэшируется в drain_watcher.routes.json (kroute route --emit) с ключом
   .routes.key: пока не менялись детали, их места, цепи падов, ручная разводка и
   CLASSES, трассировщик не запускается, медь накладывает kroute apply. --reroute -
   развести заново.
3. Чистка хвостов, каждый излом -> дуга (радиус до R_FILLET), сшивка земли via,
   затем kroute drc: дуги, из-за которых нарушен зазор, откатываются обратно в излом.

kroute ищется как в pcbnew-заглушке: переменная KROUTE, иначе свежая сборка в
репозитории kroute.
"""
import hashlib, json, math, os, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew.board import kroute_exe
from pcbhelp import mm, tomm, fill_zones

PCB = os.path.abspath(sys.argv[1])
REROUTE = "--reroute" in sys.argv
BASE = os.path.splitext(PCB)[0]
ROUTES, KEY = BASE + ".routes.json", BASE + ".routes.key"
R_FILLET = 1.0                              # мм, наибольший радиус скругления
TIMEOUT = 120                               # с, бюджет kroute route

# Ширина дорожек по цепям для kroute, мм. Остальное - из netclass (0.2).
CLASSES = {
    "pwr": (0.5, ["VBAT", "VIN", "SW", "+5V_B"]),
    "pwr4": (0.4, ["+5V", "VBUS", "+3V3", "GND"]),
    # пады USB-C - 0.3 мм с шагом 0.5: дорожка 0.2 между ними не проходит
    "usb": (0.15, ["USB_DP", "USB_DM", "CC1", "CC2"]),
}


def kroute(*args):
    """kroute с разбором JSON-ответа; сбой - выход с его сообщением."""
    r = subprocess.run([kroute_exe(), *args], capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise SystemExit("kroute %s: %s" % (args[0], (r.stderr or r.stdout).strip()[-1500:]))


def rules_toml():
    """CLASSES -> правила kroute.toml."""
    out = []
    for _, (w, nets) in sorted(CLASSES.items()):
        for n in nets:
            out.append('[[net]]\nmatch = "%s"\nwidth = %g\n' % (n, w))
    return "\n".join(out)


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

    blocked = []      # центры via и падов
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


def drc():
    """kroute drc платы (заливку он перезаливает сам, в памяти)."""
    return kroute("drc", PCB)


# медь ближе зазора: по этим видам откатываются дуги и расширения
CLEARANCE = ("clearance", "tracks_crossing", "shorting_items", "copper_edge_clearance",
             "hole_clearance", "solder_mask_bridge")
# всё, что относится к трассировке (как ok в kroute drc)
ROUTING = CLEARANCE + ("hole_to_hole", "track_width", "via_diameter", "annular_width",
                       "drill_out_of_range", "track_dangling", "via_dangling", "items_not_allowed")


def drc_bad_items():
    """uuid дорожек и via, у которых DRC нашёл нарушение зазора или пересечение."""
    bad = set()
    for v in drc().get("markers", []):
        if v.get("type") in CLEARANCE:
            bad.update(u for u in v.get("uuids", []) if u)
    return bad


def on_axis(o, pt, tol=5000):
    """Точка pt (нм) - на оси дорожки o: у концов, на отрезке или на дуге (допуск tol нм)."""
    s, e = o.GetStart(), o.GetEnd()
    if (s - pt).EuclideanNorm() <= tol or (e - pt).EuclideanNorm() <= tol:
        return True
    if o.GetClass() == "PCB_ARC":
        c = o.GetCenter()
        return abs((pt - c).EuclideanNorm() - o.GetRadius()) <= tol and o.HitTest(pt, 0)
    dx, dy = e.x - s.x, e.y - s.y
    l2 = float(dx * dx + dy * dy)
    if l2 == 0:
        return False
    u = max(0.0, min(1.0, ((pt.x - s.x) * dx + (pt.y - s.y) * dy) / l2))
    return math.hypot(s.x + u * dx - pt.x, s.y + u * dy - pt.y) <= tol


def cleanup(board):
    """Хвосты трассировки: via, к которым
    дорожки подходят только с одного слоя, и тупиковые отрезки, ведущие в никуда. Земля
    не трогается (её via сшивают заливки), ручная разводка - тоже (она заблокирована)."""
    # помечаем и пересчитываем без помеченных, удаление - в самом конце
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
            # дорожка у via концом или проходит через неё (kroute ставит via на линию)
            lays = {t.GetLayer() for t in tracks if t.GetNetCode() == v.GetNetCode() and on_axis(t, pos, r)}
            if len(lays) < 2 and not any(p.GetNetCode() == v.GetNetCode() and p.HitTest(pos) for p in pads):
                kill.add(v.m_Uuid.AsString())
        for t in tracks:
            if t.IsLocked() or t.GetNetname() == "GND":
                continue
            me = t.m_Uuid.AsString()
            for pt in (t.GetStart(), t.GetEnd()):
                # соединён с дорожкой, если конец внутри её меди: kroute примыкает
                # к дорожке сбоку (T) с точностью своей сетки, не точно на ось
                ok = any(o.m_Uuid.AsString() != me and o.GetNetCode() == t.GetNetCode()
                         and o.GetLayer() == t.GetLayer() and on_axis(o, pt, max(5000, o.GetWidth() // 2))
                         for o in tracks) \
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


def unconnected_gnd_pads():
    """(обозначение, номер) земляных падов, которые DRC считает несоединёнными."""
    out = set()
    for v in drc().get("markers", []):
        if v.get("type") != "unconnected_items":
            continue
        for it in v.get("items", []):
            m = re.match(r"Pad (\S+) \[GND\] of (\S+)", it)
            if m:
                out.add((m.group(2), m.group(1)))
    return sorted(out)


def stitch_pads(board, pads, inset=0.42):
    """Каждому земляному паду из списка - via на основную заливку нижнего слоя и
    короткая дорожка к ней. Место ищется по кругу вокруг пада: via - глубоко внутри
    основной земли снизу и внутри земли сверху, дорожка от пада до via - вся внутри
    верхней заливки (она и так отстоит от чужой меди на зазор), не в запретных зонах."""
    fills = {}
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        ly = z.GetLayer()
        ps = z.GetFilledPolysList(ly)
        fills.setdefault(ly, []).extend(ps.Outline(i) for i in range(ps.OutlineCount()))
    keep = [z.Outline() for z in board.Zones() if z.GetIsRuleArea()]
    mainb = max(fills[pcbnew.B_Cu], key=lambda c: c.Area())
    top = fills[pcbnew.F_Cu]
    ins = mm(inset)
    net = board.FindNet("GND")
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]

    def in_top(p, d):
        return any(c.PointInside(p) and c.Distance(p, True) >= d for c in top)

    added = 0
    for ref, num in pads:
        fp = board.FindFootprintByReference(ref)
        pad = next((p for p in fp.Pads() if p.GetNumber() == num), None) if fp else None
        if pad is None:
            continue
        c = pad.GetPosition()
        r0 = max(pad.GetSize().x, pad.GetSize().y) / 2
        best = None
        for rr in (0.7, 0.9, 1.1, 1.4, 1.7, 2.0):
            for k in range(24):
                a = math.radians(15 * k)
                p = pcbnew.VECTOR2I(int(c.x + (r0 + mm(rr)) * math.cos(a)), int(c.y + (r0 + mm(rr)) * math.sin(a)))
                if not (mainb.PointInside(p) and mainb.Distance(p, True) >= ins and in_top(p, ins)):
                    continue
                if any(kz.Collide(p, mm(0.45)) for kz in keep):
                    continue
                if any((v.GetPosition() - p).EuclideanNorm() < mm(0.9) for v in vias):
                    continue
                # дорожка: от края пада до via - внутри верхней заливки
                ok = True
                for s in range(1, 11):
                    q = pcbnew.VECTOR2I(int(c.x + (p.x - c.x) * s / 10), int(c.y + (p.y - c.y) * s / 10))
                    if pad.HitTest(q):
                        continue
                    if not in_top(q, mm(0.12)):
                        ok = False
                        break
                if ok:
                    best = p
                    break
            if best is not None:
                break
        if best is None:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(c)
        t.SetEnd(best)
        t.SetWidth(mm(0.2))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(net)
        board.Add(t)
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(best)
        v.SetWidth(mm(0.6))
        v.SetDrill(mm(0.3))
        v.SetNet(net)
        board.Add(v)
        vias.append(v)
        added += 1
    return added


def stitch_gnd(board, inset=0.42, step=0.2):
    """Куски земляной заливки, отрезанные дорожками от основной, - via на основную
    заливку другого слоя. Место - внутри куска и внутри основной заливки с запасом inset
    (заливка уже отстоит от чужой меди на 0.25, край via - ещё на 0.12 внутри), не в
    запретных зонах. Основная заливка слоя - самый большой её кусок."""
    fills = {}
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        ly = z.GetLayer()
        ps = z.GetFilledPolysList(ly)
        fills.setdefault(ly, []).extend(ps.Outline(i) for i in range(ps.OutlineCount()))
    keep = []
    for z in board.Zones():
        if z.GetIsRuleArea():
            keep.append(z.Outline())
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    ins = mm(inset)
    net = board.FindNet("GND")

    def deep(chain, p):
        return chain.PointInside(p) and chain.Distance(p, True) >= ins     # True - до контура

    added = 0
    for ly, other in ((pcbnew.F_Cu, pcbnew.B_Cu), (pcbnew.B_Cu, pcbnew.F_Cu)):
        if ly not in fills or other not in fills:
            continue
        main_other = max(fills[other], key=lambda c: c.Area())
        main_here = max(fills[ly], key=lambda c: c.Area())
        for isl in fills[ly]:
            if isl is main_here:
                continue
            bb = isl.BBox()
            done = False
            y = bb.GetTop()
            while y <= bb.GetBottom() and not done:
                x = bb.GetLeft()
                while x <= bb.GetRight():
                    p = pcbnew.VECTOR2I(int(x), int(y))
                    if deep(isl, p) and deep(main_other, p) and \
                            not any(k.Collide(p, mm(0.45)) for k in keep) and \
                            all((v.GetPosition() - p).EuclideanNorm() > mm(0.9) for v in vias):
                        v = pcbnew.PCB_VIA(board)
                        v.SetPosition(p)
                        v.SetWidth(mm(0.6))
                        v.SetDrill(mm(0.3))
                        v.SetNet(net)
                        board.Add(v)
                        vias.append(v)
                        added += 1
                        done = True
                        break
                    x += mm(step)
                y += mm(step)
    return added


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
    for a in gone:
        board.Remove(a)


def drc_errors():
    """Нарушения трассировки (зазоры, ширины, висящая медь) плюс несоединённое."""
    kinds = {}
    for v in drc().get("markers", []):
        t = v.get("type")
        if t == "unconnected_items" or t in ROUTING:
            kinds[t] = kinds.get(t, 0) + 1
    if kinds:
        print("   DRC:", ", ".join("%s %d" % kv for kv in sorted(kinds.items())))
    return sum(kinds.values())


def board_key(b):
    """Ключ кэша разводки - по тому, что видит трассировщик: детали и их места, цепи
    падов, ручные дорожки и via, запретные зоны, ширины цепей."""
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
    for z in b.Zones():                     # запретные зоны трассировщик тоже видит
        if z.GetIsRuleArea():
            o = z.Outline()
            rows.append("ka %s %s" % (z.GetLayerSet().FmtHex(),
                                      [(o.CVertex(i).x, o.CVertex(i).y) for i in range(o.TotalVertices())]))
    rows.append(repr(sorted(CLASSES.items())))
    rows.append("kroute t=%d" % TIMEOUT)
    return hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()


def route(reroute):
    """kroute route (или кэш routes.json) -> медь на плате."""
    key = board_key(pcbnew.LoadBoard(PCB))
    cached = os.path.exists(ROUTES) and os.path.exists(KEY) and open(KEY).read().strip() == key
    tmp = tempfile.mkdtemp(prefix="route_")
    try:
        out = os.path.join(tmp, os.path.basename(PCB))
        if cached and not reroute:
            print("kroute: плата для трассировщика не изменилась - медь из", os.path.basename(ROUTES))
            r = kroute("apply", PCB, ROUTES, "-o", out)
            print("   дорожек %d, via %d" % (r.get("segments", 0), r.get("vias", 0)))
        else:
            cfg = os.path.join(tmp, "kroute.toml")
            open(cfg, "w", encoding="utf8").write(rules_toml())
            print("kroute route (до %d с)" % TIMEOUT)
            r = kroute("route", PCB, "-c", cfg, "-t", str(TIMEOUT), "-o", out, "--emit", ROUTES)
            st = r.get("stats", {})
            print("   %s: цепей %d, дорожек %d, via %d, %.1f с" % (r.get("status"), r.get("nets_routed", 0),
                  st.get("segments", 0), st.get("vias", 0), st.get("time_s", 0)))
            for u in r.get("unrouted", []):
                print("   не разведено %s: %s" % (u.get("net"), u.get("reason")))
            for n in r.get("notes", []):
                print("  ", n)
            if r.get("status") != "complete":
                raise SystemExit("kroute route: развести полностью не удалось")
            open(KEY, "w").write(key + "\n")
        shutil.copyfile(out, PCB)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def finish():
    """После трассировки: сужения, хвосты, дуги, сшивка земли, откат дуг у нарушений."""
    b = pcbnew.LoadBoard(PCB)
    # дорожки уже 0.13 мм (сужение у узкого пада) - до 0.13: норма JLCPCB для
    # двухслойки (от 0.127); где расширение съело зазор - вернуть исходную ширину
    wide = {}
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK" and not t.IsLocked() and t.GetWidth() < mm(0.13):
            wide[t.m_Uuid.AsString()] = t.GetWidth()
            t.SetWidth(mm(0.13))
    print("убрано хвостов: %d" % cleanup(b))
    pcbnew.SaveBoard(PCB, b)
    bad = drc_bad_items() & set(wide) if wide else set()
    if bad:
        b = pcbnew.LoadBoard(PCB)
        for t in b.GetTracks():
            if t.m_Uuid.AsString() in bad:
                t.SetWidth(wide[t.m_Uuid.AsString()])
        pcbnew.SaveBoard(PCB, b)
        print("  сужения без расширения (не хватает зазора): %d" % len(bad))

    # Ручная разводка заблокирована в build.py, трассировщик её не трогал - скругляем всё.
    b = pcbnew.LoadBoard(PCB)
    recs = fillet_all(b)
    print("скруглено изломов: %d" % len(recs))
    pcbnew.SaveBoard(PCB, b)
    fill_zones(PCB)
    b = pcbnew.LoadBoard(PCB)
    n = stitch_gnd(b)
    if n:
        print("сшивка земли: via %d" % n)
        pcbnew.SaveBoard(PCB, b)
        fill_zones(PCB)
    # земляные пады, оставшиеся без связи (заливка к ним не подошла) - своя via рядом
    for _ in range(3):
        lost = unconnected_gnd_pads()
        if not lost:
            break
        b = pcbnew.LoadBoard(PCB)
        n = stitch_pads(b, lost)
        print("via у земляных падов без связи: %d из %d" % (n, len(lost)))
        if not n:
            break
        pcbnew.SaveBoard(PCB, b)
        fill_zones(PCB)
    for _ in range(4):
        bad = drc_bad_items()
        back = [r for r in recs if r["arc"] in bad or any(u in bad for u, _ in r["t"])]
        if not back:
            break
        b = pcbnew.LoadBoard(PCB)
        revert(b, back)
        pcbnew.SaveBoard(PCB, b)
        recs = [r for r in recs if r not in back]
        print("  откат скруглений у нарушений зазора: %d" % len(back))
        fill_zones(PCB)
    print("дуг на плате: %d" % len(recs))
    # после скруглений и откатов могут остаться огрызки отрезков в сотые доли мм,
    # повисшие одним концом - та же чистка хвостов ещё раз
    b = pcbnew.LoadBoard(PCB)
    n = cleanup(b)
    if n:
        print("убрано хвостов: %d" % n)
        pcbnew.SaveBoard(PCB, b)
    fill_zones(PCB)


if any(t.GetClass() == "PCB_ARC" for t in pcbnew.LoadBoard(PCB).GetTracks()):
    raise SystemExit("плата уже разведена и скруглена - сначала заново build.py")
route(REROUTE)
finish()
n = drc_errors()
if n:
    raise SystemExit("после разводки DRC: нарушений %d" % n)
print("разводка: DRC чистый")
