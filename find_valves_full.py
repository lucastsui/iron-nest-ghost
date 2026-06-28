"""List all 23 valves with their lever (dial), GameObject names, leak state, and pressure system,
   plus each HighPressureSystemManager's health + which systems are currently blocked."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ironnest_ghost as G
g=G.Ghost(); g.focus_game(); g.resolve(); g.ensure_executor()
F=g.F
def rstr(p):
    if not p: return ""
    n=g.ru32(p+0x10); return g.rpm(p+0x14, n*2).decode("utf-16-le","ignore") if 0<n<400 else ""
obj_cls=g.get_class("Object","UnityEngine",g.core)
mi_name=g.rc(F["il2cpp_class_get_method_from_name"], obj_cls, g.cstr(320,"get_name"), 0)
m_name=g.rptr(mi_name)
def goname(o):
    try:
        r=g.main_call(m_name, o, mi_name)[0]; return rstr(r) if r else ""
    except Exception: return ""

valves=g.find_objects("ValveController")
print("=== %d VALVES (each lever = its 'dial' DialInteractable) ===" % len(valves))
rows=[]
for v in valves:
    sysid=rstr(g.rptr(v+0x028)); dial=g.rptr(v+0x030)
    dmg=g.rf32(v+0x0e0) or 0.0; fixedv=g.rf32(v+0x038) or 0.0; brokenv=g.rf32(v+0x03c) or 0.0
    rows.append((goname(v), sysid, dmg, fixedv, brokenv, dial, goname(dial) if dial else ""))
for vn,sid,dmg,fx,bk,dial,dn in sorted(rows, key=lambda r:(r[1], r[0])):
    leak = "LEAKING" if dmg>0.01 else "closed"
    print("  %-22s sys=%-14s damage=%.2f [%s]  fixed=%.1f broken=%.1f  LEVER dial=0x%x '%s'"
          % (vn, sid, dmg, leak, fx, bk, dial, dn))

print("\n=== PRESSURE SYSTEMS ===")
for m in g.find_objects("HighPressureSystemManager"):
    sid=rstr(g.rptr(m+0x020)); health=g.rf32(m+0x060) or 0.0
    thr=g.rf32(m+0x02c) or 0.0; breached=g.rb(m+0x064)
    vl=g.rptr(m+0x058); n=g.ru32(vl+0x18) if vl else 0
    print("  sys=%-20s health=%.2f  alertThreshold=%.2f  breached=%s  valves=%d"
          % (sid, health, thr, bool(breached), n))

# which systems are globally BLOCKED right now (ValveBreakBlocker static HashSet)
bb=g.get_class("ValveBreakBlocker")
print("\n(blocked systems live in ValveBreakBlocker.s_blockedSystems / s_globalBlockerCount static fields)")
