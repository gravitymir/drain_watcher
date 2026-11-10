"""Пересечения courtyard соседних деталей на одном слое."""
import sys, os, itertools

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

kicadenv.quiet()
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1]); tm = pcbnew.ToMM
items = []
for fp in b.GetFootprints():
    for lay in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        try: poly = fp.GetCourtyard(lay)
        except Exception: continue
        if poly.OutlineCount() == 0: continue
        bb = poly.BBox()
        items.append((fp.GetReference(), lay, poly,
                      (tm(bb.GetLeft()), tm(bb.GetTop()), tm(bb.GetRight()), tm(bb.GetBottom()))))


def overlap(pa, pc):
    """Площадь пересечения двух courtyard. Габариты пересекаются и у деталей,
    которые на самом деле разошлись (круглое отверстие рядом с гребёнкой),
    поэтому габарит - только предварительный отсев, решает сам полигон."""
    t = pcbnew.SHAPE_POLY_SET(pa)
    try:
        t.BooleanIntersection(pc)
    except TypeError:                       # KiCad 7 требует режим
        t.BooleanIntersection(pc, pcbnew.SHAPE_POLY_SET.PM_FAST)
    return t.OutlineCount() > 0 and t.Area() > 0


bad = []
for (a, la, pa, A), (c, lc, pc, C) in itertools.combinations(items, 2):
    if a == c or la != lc: continue
    if not (A[0] < C[2] and C[0] < A[2] and A[1] < C[3] and C[1] < A[3]): continue
    if not overlap(pa, pc): continue
    ov = (min(A[2], C[2]) - max(A[0], C[0]), min(A[3], C[3]) - max(A[1], C[1]))
    bad.append((a, c, round(ov[0], 2), round(ov[1], 2)))
print("пересечений courtyard (один слой):", len(bad))
for x in sorted(set(bad))[:12]: print("  ", x)
