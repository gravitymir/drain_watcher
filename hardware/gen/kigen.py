"""Мини-генератор KiCad 7: символьная библиотека -> .kicad_sch, модель -> netlist."""
import os, re, uuid, math, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

SYMDIR = kicadenv.SYMDIR
FPDIR = kicadenv.FPDIR


# ---------------------------------------------------------------- s-expr utils
def block(s, i):
    """Вернуть подстроку сбалансированного s-выражения, начиная с '(' в позиции i."""
    d = 0
    ins = False
    k = i
    while k < len(s):
        c = s[k]
        if ins:
            if c == "\\":
                k += 2
                continue
            if c == '"':
                ins = False
        else:
            if c == '"':
                ins = True
            elif c == "(":
                d += 1
            elif c == ")":
                d -= 1
                if d == 0:
                    return s[i : k + 1]
        k += 1
    raise ValueError("unbalanced")


def children(blk):
    """Список подвыражений верхнего уровня внутри blk."""
    out = []
    d = 0
    ins = False
    k = 0
    start = None
    while k < len(blk):
        c = blk[k]
        if ins:
            if c == "\\":
                k += 2
                continue
            if c == '"':
                ins = False
        else:
            if c == '"':
                ins = True
            elif c == "(":
                d += 1
                if d == 2:
                    start = k
            elif c == ")":
                if d == 2:
                    out.append(blk[start : k + 1])
                d -= 1
        k += 1
    return out


_libcache = {}


def _libtext(lib):
    if lib not in _libcache:
        _libcache[lib] = open(os.path.join(SYMDIR, lib + ".kicad_sym")).read()
    return _libcache[lib]


def raw_symbol(lib, name):
    s = _libtext(lib)
    m = re.search(r'\(symbol "%s"' % re.escape(name), s)
    if not m:
        raise KeyError("%s:%s" % (lib, name))
    return block(s, m.start())


class Pin:
    __slots__ = ("number", "name", "etype", "x", "y", "rot", "length")

    def __init__(self, number, name, etype, x, y, rot, length):
        self.number, self.name, self.etype = number, name, etype
        self.x, self.y, self.rot, self.length = x, y, rot, length

    def __repr__(self):
        return "Pin(%s,%s)" % (self.number, self.name)


def parse_pins(blk):
    pins = []
    for m in re.finditer(r"\(pin (\w+) \w+", blk):
        pb = block(blk, m.start())
        nm = re.search(r'\(name "([^"]*)"', pb)
        nu = re.search(r'\(number "([^"]*)"', pb)
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)", pb)
        ln = re.search(r"\(length ([-\d.]+)\)", pb)
        if not (nm and nu and at):
            continue
        pins.append(
            Pin(
                nu.group(1),
                nm.group(1),
                m.group(1),
                float(at.group(1)),
                float(at.group(2)),
                float(at.group(3)),
                float(ln.group(1)) if ln else 2.54,
            )
        )
    return pins


class Symbol:
    """Разрешённый (с раскрытым extends) символ библиотеки."""

    def __init__(self, lib, name):
        self.lib, self.name = lib, name
        self.libid = "%s:%s" % (lib, name)
        blk = raw_symbol(lib, name)
        ext = re.search(r'\(extends "([^"]+)"\)', blk)
        self.parent = ext.group(1) if ext else None
        base = raw_symbol(lib, self.parent) if self.parent else blk
        self.body = []  # sub-symbol blocks (graphics + pins)
        for ch in children(base):
            if ch.startswith('(symbol "'):
                self.body.append(ch)
        self.pins = []
        for sub in self.body:
            self.pins += parse_pins(sub)
        # свойства: сначала родителя, потом переопределения потомка
        self.props = {}
        for src in ([base] if self.parent else []) + [blk]:
            for ch in children(src):
                m = re.match(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', ch)
                if m:
                    self.props[m.group(1)] = m.group(2)
        hdr = base[: base.index("(property")] if "(property" in base else base
        # KiCad 7 пишет "(pin_names (offset 1.016) hide)", KiCad 10 - тот же блок
        # в несколько строк с "(hide yes)". Разбираем сам блок, а не его написание:
        # иначе имена выводов не прячутся и "Pin_2" ложится поверх номера.
        def _hdr_block(key):
            i = hdr.find("(%s" % key)
            return block(hdr, i) if i >= 0 else ""

        pn = _hdr_block("pin_names")
        self.pin_names = pn
        self.pin_numbers_hide = _hidden(_hdr_block("pin_numbers"))
        m = re.search(r"\(offset ([-\d.]+)\)", pn)
        self.pn_offset = float(m.group(1)) if m else 0.508
        self.pn_hide = _hidden(pn)
        self.pindict = {p.number: p for p in self.pins}
        self._bbox = None

    def bbox(self):
        """Габарит символа в его собственных координатах: (xmin, ymin, xmax, ymax)."""
        if self._bbox is None:
            xs, ys = [], []
            for sub in self.body:
                for m in re.finditer(r"\((?:xy|start|end|center) ([-\d.]+) ([-\d.]+)\)", sub):
                    xs.append(float(m.group(1)))
                    ys.append(float(m.group(2)))
            for p in self.pins:
                a = math.radians(p.rot)
                xs += [p.x, p.x + math.cos(a) * p.length]
                ys += [p.y, p.y + math.sin(a) * p.length]
            self._bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)
        return self._bbox

    def lib_symbols_entry(self):
        """Блок для секции (lib_symbols ...) схемы, с плоским (без extends) телом."""
        out = []
        out.append('    (symbol "%s" %s(pin_names (offset %g)%s) (in_bom yes) (on_board yes)'
                   % (self.libid,
                      "(pin_numbers hide) " if self.pin_numbers_hide else "",
                      self.pn_offset,
                      " hide" if self.pn_hide else ""))
        order = ["Reference", "Value", "Footprint", "Datasheet"]
        keys = order + [k for k in self.props if k not in order]
        for i, k in enumerate(keys):
            v = self.props.get(k, "")
            hide = "" if k in ("Reference", "Value") else " hide"
            out.append('      (property "%s" "%s" (at 0 %g 0)\n        (effects (font (size 1.27 1.27))%s)\n      )'
                       % (k, v, 20 + i * 2.54, hide))
        for sub in self.body:
            newname = re.match(r'\(symbol "([^"]+)"', sub).group(1)
            suffix = newname[len(self.parent):] if self.parent and newname.startswith(self.parent) else newname[len(self.name):]
            sub2 = sub.replace('(symbol "%s"' % newname, '(symbol "%s%s"' % (self.name, suffix), 1)
            out.append("      " + sub2)
        out.append("    )")
        return "\n".join(out)


def _hidden(blk):
    """Флаг hide внутри блока - в обоих написаниях, KiCad 7 и KiCad 10."""
    return bool(blk) and (re.search(r"\(hide\s+yes\)", blk) is not None
                          or re.search(r"\bhide\s*\)", blk) is not None)


_symcache = {}


def get_symbol(libid):
    if libid not in _symcache:
        lib, name = libid.split(":", 1)
        _symcache[libid] = Symbol(lib, name)
    return _symcache[libid]


# ---------------------------------------------------------------- модель схемы
class Part:
    def __init__(self, ref, libid, value, footprint, nets, at=(0, 0), datasheet="~", dnp=False):
        self.ref, self.libid, self.value, self.footprint = ref, libid, value, footprint
        self.nets = dict(nets)          # {pin_number: net_name}
        self.at = at
        self.datasheet = datasheet
        self.dnp = dnp
        self.sym = get_symbol(libid)
        for pn in self.nets:
            if pn not in self.sym.pindict:
                raise KeyError("%s: нет вывода %s в %s" % (ref, pn, libid))

    def pinpos(self, number):
        p = self.sym.pindict[number]
        return (self.at[0] + p.x, self.at[1] - p.y)


class Design:
    def __init__(self, name, title, paper="A2"):
        self.name, self.title, self.paper = name, title, paper
        self.parts = []
        self.extra_labels = []

    def add(self, part):
        self.parts.append(part)
        return part

    def nets(self):
        d = {}
        for p in self.parts:
            for pn, net in p.nets.items():
                d.setdefault(net, []).append((p.ref, pn))
        return d

    # ------------------------------------------------------------- schematic
    def write_sch(self, path):
        U = lambda: str(uuid.uuid4())
        libids = []
        for p in self.parts:
            if p.libid not in libids:
                libids.append(p.libid)
        o = []
        o.append("(kicad_sch (version 20230121) (generator kigen)")
        o.append("  (uuid %s)" % U())
        o.append('  (paper "%s")' % self.paper)
        o.append("  (title_block")
        o.append('    (title "%s")' % self.title)
        o.append('    (company "")')
        o.append("  )")
        o.append("  (lib_symbols")
        for lid in libids:
            o.append(get_symbol(lid).lib_symbols_entry())
        o.append("  )")

        wires, labels = [], []
        for p in self.parts:
            sy = p.sym
            for pn, net in sorted(p.nets.items()):
                pin = sy.pindict[pn]
                cx, cy = p.pinpos(pn)
                out = math.radians(pin.rot + 180.0)
                dx, dy = math.cos(out), -math.sin(out)
                L = 5.08
                ex, ey = round(cx + dx * L, 4), round(cy + dy * L, 4)
                wires.append((cx, cy, ex, ey))
                ang = (pin.rot + 180.0) % 360.0
                labels.append((net, ex, ey, ang))
        for net, x, y, a in labels:
            # текст метки уходит от точки привязки наружу: вправо/вверх - left, влево/вниз - right
            just = "right" if a in (180.0, 270.0) else "left"
            o.append('  (global_label "%s" (shape passive) (at %g %g %g) (fields_autoplaced)' % (net, x, y, a))
            o.append("    (effects (font (size 1.27 1.27)) (justify %s))" % just)
            o.append("    (uuid %s)" % U())
            o.append('    (property "Intersheet References" "${INTERSHEET_REFS}" (at %g %g %g)' % (x, y, a))
            o.append("      (effects (font (size 1.27 1.27)) (justify %s) hide)" % just)
            o.append("    )")
            o.append("  )")
        # свободные выводы - крестик no_connect, иначе ERC ругается, а плата получает
        # для их падов искусственные цепи unconnected-(...)
        for p in self.parts:
            if p.ref.startswith("#") or not p.nets:
                continue
            for pin in p.sym.pins:
                if pin.number in p.nets or pin.etype == "no_connect":
                    continue
                if any(q.number in p.nets for q in p.sym.pins if q is not pin and q.name == pin.name
                       and abs(q.x - pin.x) < 1e-6 and abs(q.y - pin.y) < 1e-6):
                    continue                # сложенный вывод (тот же пин, другой номер)
                x, y = p.pinpos(pin.number)
                o.append("  (no_connect (at %g %g) (uuid %s))" % (x, y, U()))
        for x1, y1, x2, y2 in wires:
            o.append("  (wire (pts (xy %g %g) (xy %g %g))" % (x1, y1, x2, y2))
            o.append("    (stroke (width 0) (type default))")
            o.append("    (uuid %s)" % U())
            o.append("  )")

        for p in self.parts:
            su = U()
            # Reference/Value ставим над символом, выше всего, что рисуется вокруг него,
            # включая метки, уходящие вверх - иначе они наезжают на тело символа
            x0, y0, x1, y1 = p.sym.bbox()
            top = p.at[1] - y1
            for pn, net in p.nets.items():
                pin = p.sym.pindict[pn]
                if (pin.rot + 180.0) % 360.0 == 90.0:   # провод и вертикальная метка уходят вверх
                    top = min(top, p.at[1] - pin.y - 5.08 - 1.6 - 0.95 * len(net))
            if x1 - x0 < 6.0:
                # узкие двухвыводные детали: имя и номинал сбоку, иначе метки их накрывают
                rx, ry, vy = p.at[0] + x1 + 1.0, p.at[1] - 1.27, p.at[1] + 1.27
            else:
                rx, ry, vy = p.at[0] + x0, top - 3.81, top - 1.27
            o.append('  (symbol (lib_id "%s") (at %g %g 0) (unit 1)' % (p.libid, p.at[0], p.at[1]))
            o.append("    (in_bom %s) (on_board yes) (dnp %s) (fields_autoplaced)"
                     % ("yes" if getattr(p, "in_bom", True) else "no", "yes" if p.dnp else "no"))
            o.append("    (uuid %s)" % su)
            o.append('    (property "Reference" "%s" (at %g %g 0)' % (p.ref, rx, ry))
            o.append("      (effects (font (size 1.27 1.27)) (justify left))")
            o.append("    )")
            o.append('    (property "Value" "%s" (at %g %g 0)' % (p.value, rx, vy))
            o.append("      (effects (font (size 1.27 1.27)) (justify left))")
            o.append("    )")
            o.append('    (property "Footprint" "%s" (at %g %g 0)' % (p.footprint, p.at[0], p.at[1]))
            o.append("      (effects (font (size 1.27 1.27)) hide)")
            o.append("    )")
            o.append('    (property "Datasheet" "%s" (at %g %g 0)' % (p.datasheet, p.at[0], p.at[1]))
            o.append("      (effects (font (size 1.27 1.27)) hide)")
            o.append("    )")
            for pin in p.sym.pins:
                o.append('    (pin "%s" (uuid %s))' % (pin.number, U()))
            o.append('    (instances')
            o.append('      (project "%s"' % self.name)
            o.append('        (path "/%s" (reference "%s") (unit 1))' % (self.root_uuid, p.ref))
            o.append("      )")
            o.append("    )")
            o.append("  )")
        o.append('  (sheet_instances')
        o.append('    (path "/" (page "1"))')
        o.append("  )")
        o.append(")")
        open(path, "w").write("\n".join(o) + "\n")

    root_uuid = property(lambda self: self._ru)

    def prepare(self):
        self._ru = str(uuid.uuid4())
