"""Хелперы поверх pcbnew 7 для скриптовой сборки плат."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

kicadenv.quiet()
import pcbnew

FPDIR = kicadenv.FPDIR


def mm(v):
    return pcbnew.FromMM(float(v))


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def tomm(v):
    return pcbnew.ToMM(v)


class Builder:
    def __init__(self, layers=4):
        self.b = pcbnew.BOARD()
        self.b.SetCopperLayerCount(layers)
        ds = self.b.GetDesignSettings()
        ds.SetCopperLayerCount(layers)
        self.nets = {}
        self.fps = {}
        self._setup_rules()

    def _setup_rules(self):
        ds = self.b.GetDesignSettings()
        ds.m_TrackMinWidth = mm(0.15)
        ds.m_ViasMinSize = mm(0.45)
        ds.m_MinThroughDrill = mm(0.3)      # JLCPCB, 2 слоя: сверло от 0.3 мм
        ds.m_HoleToHoleMin = mm(0.25)
        ds.m_HoleClearance = mm(0.2)
        ds.m_CopperEdgeClearance = mm(0.3)

    # ---------------------------------------------------------------- nets
    def net(self, name):
        if name not in self.nets:
            n = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(n)
            self.nets[name] = n
        return self.nets[name]

    # ---------------------------------------------------------- footprints
    def place(self, ref, lib, name, x, y, rot=0.0, back=False, value=""):
        fp = pcbnew.FootprintLoad("%s/%s.pretty" % (FPDIR, lib), name)
        if fp is None:
            raise KeyError("%s:%s" % (lib, name))
        fp.SetFPID(pcbnew.LIB_ID(lib, name))     # без имени библиотеки KiCad ругается на несоответствие схеме
        fp.SetReference(ref)
        fp.SetValue(value or name)
        self.b.Add(fp)
        if back:
            fp.Flip(fp.GetPosition(), False)
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        fp.Reference().SetVisible(True)
        fp.Value().SetVisible(False)
        self.fps[ref] = fp
        return fp

    def set_model(self, ref, path, hide_others=True):
        """Подменить 3D-модель компонента (для футпринтов без модели в библиотеке)."""
        import pcbnew as _p
        fp = self.fps[ref]
        m = _p.FP_3DMODEL()
        m.m_Filename = path
        m.m_Show = True
        try:
            fp.Models().clear()
        except Exception:
            pass
        fp.Add3DModel(m)

    @staticmethod
    def pad_zone_connection(pad, mode):
        """KiCad 10 переименовал PAD::SetZoneConnection в SetLocalZoneConnection."""
        fn = getattr(pad, "SetLocalZoneConnection", None) or pad.SetZoneConnection
        fn(mode)

    def pad(self, ref, num):
        for p in self.fps[ref].Pads():
            if p.GetNumber() == str(num):
                return p
        raise KeyError("%s pad %s" % (ref, num))

    def padxy(self, ref, num):
        p = self.pad(ref, num).GetPosition()
        return (tomm(p.x), tomm(p.y))

    def setnet(self, ref, num, netname):
        n = self.net(netname)
        found = False
        for p in self.fps[ref].Pads():
            if p.GetNumber() == str(num):
                p.SetNet(n)
                found = True
        if not found:
            raise KeyError("%s pad %s" % (ref, num))

    # -------------------------------------------------------------- routing
    def track(self, netname, pts, layer=pcbnew.F_Cu, width=0.2):
        n = self.net(netname)
        for i in range(len(pts) - 1):
            if pts[i] == pts[i + 1]:        # вырожденный отрезок KiCad считает ошибкой
                continue
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(V(*pts[i]))
            t.SetEnd(V(*pts[i + 1]))
            t.SetWidth(mm(width))
            t.SetLayer(layer)
            t.SetNet(n)
            self.b.Add(t)

    def via(self, netname, x, y, dia=0.5, drill=0.25):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(V(x, y))
        v.SetWidth(mm(dia))
        v.SetDrill(mm(drill))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(netname))
        self.b.Add(v)
        return v

    # --------------------------------------------------------------- shapes
    def edge_rect(self, cx, cy, w, h, r=3.0):
        """Прямоугольный контур платы со скруглёнными углами."""
        x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        segs = [
            ((x0 + r, y0), (x1 - r, y0)),
            ((x1, y0 + r), (x1, y1 - r)),
            ((x1 - r, y1), (x0 + r, y1)),
            ((x0, y1 - r), (x0, y0 + r)),
        ]
        for a, b in segs:
            s = pcbnew.PCB_SHAPE(self.b)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(V(*a))
            s.SetEnd(V(*b))
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(mm(0.1))
            self.b.Add(s)
        arcs = [
            ((x0 + r, y0 + r), 180, 270),
            ((x1 - r, y0 + r), 270, 360),
            ((x1 - r, y1 - r), 0, 90),
            ((x0 + r, y1 - r), 90, 180),
        ]
        for (ax, ay), a0, a1 in arcs:
            s = pcbnew.PCB_SHAPE(self.b)
            s.SetShape(pcbnew.SHAPE_T_ARC)
            am = math.radians((a0 + a1) / 2.0)
            s.SetStart(V(ax + r * math.cos(math.radians(a0)), ay + r * math.sin(math.radians(a0))))
            s.SetEnd(V(ax + r * math.cos(math.radians(a1)), ay + r * math.sin(math.radians(a1))))
            s.SetCenter(V(ax, ay))
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(mm(0.1))
            self.b.Add(s)

    def mounting_hole(self, x, y, drill=2.2, pad=4.0, netname="GND"):
        fp = pcbnew.FootprintLoad("%s/MountingHole.pretty" % FPDIR,
                                  "MountingHole_2.2mm_M2_Pad_Via")
        if fp is None:
            return None
        self.b.Add(fp)
        fp.SetPosition(V(x, y))
        fp.SetReference("H%d" % (len([f for f in self.fps if f.startswith("H")]) + 1))
        self.fps[fp.GetReference()] = fp
        for p in fp.Pads():
            p.SetNet(self.net(netname))
        return fp

    def pad_axis(self, ref):
        """Ось между двумя падами двухвыводного компонента (единичный вектор) или None."""
        ps = list(self.fps[ref].Pads())
        nums = sorted({p.GetNumber() for p in ps})
        if len(nums) != 2:
            return None
        a = self.padxy(ref, nums[0]); c = self.padxy(ref, nums[1])
        import math as _m
        dx, dy = c[0] - a[0], c[1] - a[1]
        L = _m.hypot(dx, dy) or 1.0
        return (dx / L, dy / L)

    def zone(self, netname, layer, cx, cy, w, h):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        z.SetNet(self.net(netname))
        z.SetIsFilled(True)
        z.SetLocalClearance(mm(0.25))
        z.SetMinThickness(mm(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.3))
        z.SetThermalReliefSpokeWidth(mm(0.4))
        o = z.Outline()
        o.NewOutline()
        x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        for p in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            o.Append(mm(p[0]), mm(p[1]))
        self.b.Add(z)
        return z

    def text(self, s, x, y, layer=pcbnew.F_SilkS, size=1.0, thick=0.15, rot=0, mirror=False):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(V(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(thick))
        t.SetTextAngleDegrees(rot)
        t.SetMirrored(mirror)
        self.b.Add(t)
        return t

    # ----------------------------------------------------------------- save
    def finish(self, path, fill=True):
        self.b.BuildListOfNets()
        try:
            self.b.BuildConnectivity()
        except Exception:
            pass
        pcbnew.SaveBoard(path, self.b)
        if fill:
            fill_zones(path)


def footprint_save(libdir, fp):
    """Сохранить футпринт в .pretty рядом с проектом.

    pcbnew.FootprintSave угадывает формат библиотеки по её содержимому, а каталог
    у нас пустой - в KiCad 10 угадывание промахивается. Формат KiCad задаём явно.
    """
    mgr = getattr(pcbnew, "PCB_IO_MGR", None)
    if mgr is not None:
        mgr.FindPlugin(mgr.KICAD_SEXP).FootprintSave(libdir, fp)
    else:
        pcbnew.FootprintSave(libdir, fp)     # KiCad 7


def fill_zones(path):
    """Заливка полигонов: делается на заново загруженной плате (иначе KiCad 7 падает)."""
    import subprocess, sys, os
    code = (
        "import pcbnew,sys\n"
        "b=pcbnew.LoadBoard(sys.argv[1])\n"
        "b.BuildListOfNets()\n"
        "pcbnew.ZONE_FILLER(b).Fill(b.Zones())\n"
        "pcbnew.SaveBoard(sys.argv[1], b)\n"
        "print('zones filled:', len(b.Zones()))\n"
    )
    r = subprocess.run([sys.executable, "-c", code, path], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip()[-400:])
    return r.returncode == 0
