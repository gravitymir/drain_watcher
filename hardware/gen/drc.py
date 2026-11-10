#!/usr/bin/env python3
"""Геометрический DRC: зазоры между дорожками/via/падами разных цепей + несоединённые цепи."""
import sys, math, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

kicadenv.quiet()
import pcbnew

CLR = 0.2
CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
ALLCU = frozenset(CU)


def seg_dist(p, q, r, s):
    def d(ax, ay, bx, by):
        return math.hypot(ax - bx, ay - by)

    def pt_seg(px, py, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            return d(px, py, ax, ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        return d(px, py, ax + t * dx, ay + t * dy)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1, d2 = cross(r, s, p), cross(r, s, q)
    d3, d4 = cross(p, q, r), cross(p, q, s)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(pt_seg(*p, *r, *s), pt_seg(*q, *r, *s), pt_seg(*r, *p, *q), pt_seg(*s, *p, *q))


class It:
    __slots__ = ("kind", "nc", "nm", "lay", "a", "bb", "hw", "lbl", "owner")


def collect(b):
    tomm = pcbnew.ToMM
    out = []
    for t in b.GetTracks():
        i = It()
        i.nc, i.nm, i.owner = t.GetNetCode(), t.GetNetname(), None
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            i.kind, i.lay = "via", ALLCU
            i.a = i.bb = (tomm(p.x), tomm(p.y))
            i.hw = tomm(t.GetWidth()) / 2
            i.lbl = "via"
        else:
            s, e = t.GetStart(), t.GetEnd()
            i.kind, i.lay = "trk", frozenset([t.GetLayer()])
            i.a, i.bb = (tomm(s.x), tomm(s.y)), (tomm(e.x), tomm(e.y))
            i.hw = tomm(t.GetWidth()) / 2
            i.lbl = "track"
        out.append(i)
    for fp in b.GetFootprints():
        for p in fp.Pads():
            i = It()
            i.kind, i.nc, i.nm, i.owner = "pad", p.GetNetCode(), p.GetNetname(), fp.GetReference()
            i.lay = frozenset(l for l in p.GetLayerSet().Seq() if l in ALLCU)
            sz = p.GetSize()
            sx, sy = tomm(sz.x), tomm(sz.y)
            i.hw = min(sx, sy) / 2.0
            ext = (max(sx, sy) - min(sx, sy)) / 2.0
            ang = math.radians(p.GetOrientationDegrees() + (0 if sx >= sy else 90))
            pos = p.GetPosition()
            cx, cy = tomm(pos.x), tomm(pos.y)
            dx, dy = math.cos(ang) * ext, -math.sin(ang) * ext
            i.a, i.bb = (cx - dx, cy - dy), (cx + dx, cy + dy)
            i.lbl = "%s.%s" % (fp.GetReference(), p.GetNumber())
            if not i.lay:
                continue
            out.append(i)
    return out


def run(path, limit=60, clr=CLR):
    b = pcbnew.LoadBoard(path)
    b.BuildListOfNets()
    items = collect(b)
    errs = []
    n = len(items)
    for x in range(n):
        i = items[x]
        for y in range(x + 1, n):
            j = items[y]
            if i.nc == j.nc and i.nc != 0:
                continue
            if i.owner is not None and i.owner == j.owner:
                continue
            if not (i.lay & j.lay):
                continue
            dd = seg_dist(i.a, i.bb, j.a, j.bb) - i.hw - j.hw
            if dd < clr - 1e-6:      # ровно по правилу - не нарушение (KiCad считает в нм)
                errs.append((round(dd, 3), "%s(%s)[%.1f,%.1f-%.1f,%.1f] <-> %s(%s)[%.1f,%.1f]"
                             % (i.lbl, i.nm or "-", i.a[0], i.a[1], i.bb[0], i.bb[1],
                                j.lbl, j.nm or "-", j.a[0], j.a[1])))
    errs.sort()
    conn = b.GetConnectivity()
    conn.RecalculateRatsnest()
    unconn = conn.GetUnconnectedCount(True)
    print("=== %s" % path.split("/")[-1])
    print("нетов %d | дорожек+via %d | нарушений зазора %d | несоединённых %d"
          % (b.GetNetCount(), len(b.GetTracks()), len(errs), unconn))
    for e in errs[:limit]:
        print("  %+.3f  %s" % e)
    return errs, unconn


if __name__ == "__main__":
    run(sys.argv[1])
