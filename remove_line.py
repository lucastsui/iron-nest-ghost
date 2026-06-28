"""Remove the red targeting line(s) - final step of a shoot-and-forget fire mission."""
import sys, struct, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ironnest_ghost as G
g=G.Ghost(); g.focus_game(); g.resolve(); g.ensure_executor()
import time as _t
_omc=g.main_call
def _mc(*a,**k):
    r=_omc(*a,**k)
    for _ in range(8):
        if r[0] is not None: return r
        g.focus_game(); _t.sleep(0.15); r=_omc(*a,**k)
    return r
g.main_call=_mc
def meth(cls,name,argc):
    mi=g.rc(g.F["il2cpp_class_get_method_from_name"],cls,g.cstr(320,name),argc); return g.rptr(mi),mi
comp_cls=g.get_class("Component","UnityEngine",g.core); obj_cls=g.get_class("Object","UnityEngine",g.core)
m_go=meth(comp_cls,"get_gameObject",0)
dmi=g.rc(g.F["il2cpp_class_get_method_from_name"],obj_cls,g.cstr(320,"Destroy"),1)
pls=g.find_objects("MapMarkerPlacer")
if pls: g.wpm(g.rptr(pls[0]+0x88)+0x18, struct.pack("<i",0))   # clear placedMarkers (avoid dead refs)
removed=0
for L in g.find_objects("MapMarkerLineUI"):
    go=g.main_call(m_go[0], L, m_go[1])[0]
    if go: g.main_call(g.rptr(dmi), go, dmi); removed+=1
print("red targeting line removed (%d)"%removed)
