"""Read-only: dump both guns' reload state / breech / chamber so we know it's safe to drive."""
import sys, os
GHOST=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, GHOST)
import ironnest_ghost as G

def rstr(g,p):
    if not p: return ""
    n=g.ru32(p+0x10); return g.rpm(p+0x14,n*2).decode("utf-16-le","ignore") if 0<n<400 else ""
def gn(g,gp): return rstr(g, g.rptr(gp+0x20))

g=G.Ghost(); g.focus_game(); g.resolve(); g.ensure_executor()
gun_cls=g.get_class("GunController")
F=g.F
def meth(cls,name,argc):
    mi=g.rc(F["il2cpp_class_get_method_from_name"],cls,g.cstr(320,name),argc); return g.rptr(mi),mi
m_can=meth(gun_cls,"get_CanFire",0)

for r in g.find_objects("ArtilleryReloadController"):
    name=gn(g, g.rptr(r+0x68))
    gun=g.rptr(r+0x68)
    cyl=[c for c in g.find_objects("CylinderShellSelector") if g.rptr(c+0x40)==r]
    cyl=cyl[0] if cyl else 0
    lst=g.rptr(r+0x28); it2=g.rptr(lst+0x10)
    names={i: rstr(g, g.rptr(g.rptr(it2+0x20+i*8)+0x10)) for i in range(g.ru32(lst+0x18))}
    st=g.ru32(r+0x48); stname=names.get(st,"?")
    breech=g.rb(cyl+0x88) if cyl else None
    chambered=g.rptr(r+0x38)!=0
    canfire=((g.main_call(m_can[0],gun,m_can[1])[0] or 0)&0xff)==1
    # occupancy
    occ=[]
    if cyl:
        bl=g.rptr(cyl+0x30); bit=g.rptr(bl+0x10); nb=g.ru32(bl+0x18) if bl else 0
        occ=[bool(g.rptr(bit+0x20+i*8)) for i in range(nb)] if 0<nb<=12 else []
    print("%-9s reloadState=%d(%s) breech=%s chambered=%s CanFire=%s occ=%s elev=%.1f" %
          (name, st, stname, breech, chambered, canfire, occ, g.rf32(gun+0xb4)))
