import sys, math, itertools, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

kicadenv.quiet()
import pcbnew
tomm=pcbnew.ToMM
def rect(cx,cy,w,h,ang):
    a=math.radians(-ang); ca,sa=math.cos(a),math.sin(a)
    return [(cx+dx*ca-dy*sa, cy+dx*sa+dy*ca) for dx,dy in
            ((-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2))]
def sat(A,B,gap=0.0):
    """Возвращает глубину проникновения (мм) или 0, если не пересекаются."""
    best=1e9
    for P,Q in ((A,B),(B,A)):
        for i in range(4):
            ex,ey=P[(i+1)%4][0]-P[i][0], P[(i+1)%4][1]-P[i][1]
            nx,ny=-ey,ex; L=math.hypot(nx,ny) or 1; nx,ny=nx/L,ny/L
            a=[p[0]*nx+p[1]*ny for p in P]; b=[p[0]*nx+p[1]*ny for p in Q]
            if min(a)-gap > max(b) or min(b)-gap > max(a): return 0.0
            best=min(best, min(max(a)-min(b), max(b)-min(a)))
    return best
b=pcbnew.LoadBoard(sys.argv[1])
LAY=(pcbnew.F_SilkS,pcbnew.B_SilkS)
texts={l:[] for l in LAY}; pads={l:[] for l in LAY}
def addtxt(t,name):
    if t.GetLayer() not in LAY or not t.IsVisible(): return
    bx=kicadenv.textbox(t); p=t.GetPosition()
    texts[t.GetLayer()].append((rect(tomm(p.x),tomm(p.y),tomm(bx.GetWidth()),tomm(bx.GetHeight()),
                                     t.GetTextAngleDegrees()), name))
for fp in b.GetFootprints():
    addtxt(fp.Reference(), fp.GetReference()+':ref')
    addtxt(fp.Value(), fp.GetReference()+':val')
    for p in fp.Pads():
        ls=set(p.GetLayerSet().Seq()); sz=p.GetSize()
        for cu,sk in ((pcbnew.F_Cu,pcbnew.F_SilkS),(pcbnew.B_Cu,pcbnew.B_SilkS)):
            if cu in ls:
                q=p.GetPosition()
                pads[sk].append((rect(tomm(q.x),tomm(q.y),tomm(sz.x),tomm(sz.y),p.GetOrientationDegrees()),
                                 fp.GetReference()+'.'+p.GetNumber()))
for d in b.GetDrawings():
    if d.GetClass()=='PCB_TEXT': addtxt(d, '"%s"'%d.GetText())
# Контур платы: шелк за ним при печати обрезается.
bb=b.GetBoardEdgesBoundingBox()
BX0,BY0=tomm(bb.GetLeft()),tomm(bb.GetTop())
BX1,BY1=tomm(bb.GetRight()),tomm(bb.GetBottom())
THR=float(sys.argv[2]) if len(sys.argv)>2 else 0.0
ov=[];op=[];oe=[]
for l in LAY:
    for (A,na) in texts[l]:
        xs=[q[0] for q in A]; ys=[q[1] for q in A]
        m=min(min(xs)-BX0, BX1-max(xs), min(ys)-BY0, BY1-max(ys))
        if m<0: oe.append((round(-m,2),na,'контур'))
    for (A,na),(B,nb) in itertools.combinations(texts[l],2):
        d=sat(A,B)
        if d>THR: ov.append((round(d,2),na,nb))
    for (A,na) in texts[l]:
        for (B,nb) in pads[l]:
            d=sat(A,B)
            if d>THR: op.append((round(d,2),na,nb))
print('надписей: %d | текст-текст: %d | поверх пада: %d | за контуром платы: %d'
      % (sum(len(texts[l]) for l in LAY), len(ov), len(op), len(oe)))
ov.sort(reverse=True)
op.sort(reverse=True)
oe.sort(reverse=True)
for x in ov: print('   TT %5.2f мм  %s <-> %s' % x)
for x in op: print('   TP %5.2f мм  %s <-> %s' % x)
for x in oe: print('   TE %5.2f мм  %s за %s платы' % x)
