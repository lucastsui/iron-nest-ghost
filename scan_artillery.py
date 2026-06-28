import sys, struct, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ironnest_ghost as G
g=G.Ghost(); g.resolve()
def rstr(p):
    if not p: return ""
    n=g.ru32(p+0x10); return g.rpm(p+0x14,n*2).decode("utf-16-le","ignore") if 0<n<400 else ""
fm=g.find_one("FireMission")
d=g.rptr(fm+0x78); entries=g.rptr(d+0x18); cnt=g.ru32(d+0x20)
ids=[]
for i in range(cnt):
    val=g.rptr(entries+0x20+i*0x18+0x10)
    if not val: continue
    icon=rstr(g.rptr(val+0x20)); hp=struct.unpack("<i", g.rpm(val+0x68,4) or b"\0\0\0\0")[0]
    if "field artillery" in icon.lower() and "observer" not in icon.lower() and hp>0:
        ids.append((rstr(g.rptr(val+0x10)), rstr(g.rptr(val+0x18))))
print("ARTILLERY_LIVE:"+",".join(i for i,_ in ids))
for i,n in ids: print("  %s = %s"%(i,n))
