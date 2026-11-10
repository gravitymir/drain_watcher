import math, sys, os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicadenv

kicadenv.quiet()
import pcbnew
b=pcbnew.LoadBoard(sys.argv[1]); tm=pcbnew.ToMM
ALL={pcbnew.F_Cu,pcbnew.In1_Cu,pcbnew.In2_Cu,pcbnew.B_Cu}
ZONE={z.GetNetname() for z in b.Zones()}
items=defaultdict(list)
for t in b.GetTracks():
    n=t.GetNetname()
    if t.GetClass()=="PCB_VIA":
        p=t.GetPosition(); g=((tm(p.x),tm(p.y)),(tm(p.x),tm(p.y))); lay=ALL
    else:
        s,e=t.GetStart(),t.GetEnd(); g=((tm(s.x),tm(s.y)),(tm(e.x),tm(e.y))); lay={t.GetLayer()}
    items[n].append((g,lay,tm(t.GetWidth())/2,"trk"))
for fp in b.GetFootprints():
    for p in fp.Pads():
        n=p.GetNetname()
        if not n: continue
        pos=p.GetPosition(); sz=p.GetSize(); sx,sy=tm(sz.x),tm(sz.y)
        half=min(sx,sy)/2; ext=(max(sx,sy)-min(sx,sy))/2
        ang=math.radians(p.GetOrientationDegrees()+(0 if sx>=sy else 90))
        cx,cy=tm(pos.x),tm(pos.y); dx,dy=math.cos(ang)*ext,-math.sin(ang)*ext
        lay={l for l in p.GetLayerSet().Seq() if l in ALL}
        items[n].append((((cx-dx,cy-dy),(cx+dx,cy+dy)),lay,half,"%s.%s"%(fp.GetReference(),p.GetNumber())))
def sd(p,q,r,s):
    def ps(px,py,ax,ay,bx,by):
        dx,dy=bx-ax,by-ay; L=dx*dx+dy*dy
        if L==0: return math.hypot(px-ax,py-ay)
        t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/L)); return math.hypot(px-ax-t*dx,py-ay-t*dy)
    return min(ps(*p,*r,*s),ps(*q,*r,*s),ps(*r,*p,*q),ps(*s,*p,*q))
bad=0
for net,its in sorted(items.items()):
    if net in ZONE: continue
    n=len(its); par=list(range(n))
    def find(x, par=par):
        while par[x]!=x: par[x]=par[par[x]]; x=par[x]
        return x
    for i in range(n):
        for j in range(i+1,n):
            if not (its[i][1]&its[j][1]): continue
            if sd(its[i][0][0],its[i][0][1],its[j][0][0],its[j][0][1]) <= its[i][2]+its[j][2]+0.02:
                a,c=find(i),find(j)
                if a!=c: par[a]=c
    comps=defaultdict(list)
    for i in range(n): comps[find(i)].append(its[i][3])
    if len(comps)>1:
        bad+=1
        print("РАЗРЫВ:",net)
        for k,(root,mem) in enumerate(comps.items()):
            print("   группа%d:"%k, [m for m in mem if m!="trk"] or "(только дорожки)")
print("несвязных цепей:", bad)
