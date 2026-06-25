"""Read-only: print live ENEMY entity IDs (any 'Enemy' icon, hp>0) for the pipeline's target picker.
Draws NOTHING -> no line-drawing sound. Includes hostile units AND artillery (more targets)."""
import sys, struct
GHOST=r"C:\Users\Owner\Desktop\Iron Nest Hack"
sys.path.insert(0, GHOST)
import ironnest_ghost as G
g=G.Ghost(); g.focus_game(); g.resolve()
def rstr(p):
    if not p: return ""
    n=g.ru32(p+0x10); return g.rpm(p+0x14,n*2).decode("utf-16-le","ignore") if 0<n<400 else ""
fm=g.find_one("FireMission")
d=g.rptr(fm+0x78); entries=g.rptr(d+0x18); cnt=g.ru32(d+0x20)
live=[]
for i in range(cnt):
    val=g.rptr(entries+0x20+i*0x18+0x10)
    if not val: continue
    nm=rstr(g.rptr(val+0x10)); icon=rstr(g.rptr(val+0x20))
    if icon.startswith("Enemy"):                       # all enemy units, incl. field artillery + observers
        hp=struct.unpack("<i", g.rpm(val+0x68,4) or b"\0\0\0\0")[0]
        if hp>0: live.append(nm)
print("ENEMIES_LIVE:"+",".join(live))
