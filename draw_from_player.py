"""
Draw PLAYER -> target line. Player origin comes from the GAME'S GRID SYSTEM:
CodeToLocal('D5 2:2') -> exact local position. Target = nearest hostile tank (also
reported by its grid code). Full learned recipe (parent MapMarkers, localPosition=origin,
identity rotation, Initialize+UpdateLine, SetLabelsVisible, add to placedMarkers).
  usage: python draw_from_player.py [PLAYER_CODE='D5 2:2'] [targetName]
"""
import sys, struct, math, time, os, random
sys.path.insert(0, r"C:\Users\Owner\Desktop\Iron Nest Hack")
import ironnest_ghost as G
g=G.Ghost(); g.focus_game(); g.resolve(); g.ensure_executor()
F=g.F
import time as _t
_omc=g.main_call
def _mc(*a,**k):
    r=_omc(*a,**k)
    for _ in range(8):
        if r[0] is not None: return r
        g.focus_game(); _t.sleep(0.15); r=_omc(*a,**k)
    return r
g.main_call=_mc
import ironnest_probe as P
rvas=P.export_rvas(P.DLL)
for n in ["il2cpp_method_get_param","il2cpp_method_get_param_count","il2cpp_type_get_name",
          "il2cpp_class_get_methods","il2cpp_method_get_name","il2cpp_string_new"]:
    if n in rvas: F[n]=g.base+rvas[n]
TARGET=sys.argv[1] if len(sys.argv)>1 else None        # "RANDOM" | entity name | None(=nearest hostile)
PLAYER_CODE=os.environ.get("IRN_PLAYER")               # optional grid-code override; else auto-read
def rstr(p):
    if not p: return ""
    n=g.ru32(p+0x10); return g.rpm(p+0x14,n*2).decode("utf-16-le","ignore") if 0<n<400 else ""
def rcstr(a,m=128):
    if not a: return ""
    r=g.rpm(a,m); z=r.find(b'\0') if r else -1; return r[:z].decode(errors="ignore") if r else ""
def meth(cls,name,argc):
    mi=g.rc(F["il2cpp_class_get_method_from_name"],cls,g.cstr(320,name),argc); return g.rptr(mi),mi
def find_method(cls,name,ptypes):
    itp=G.VirtualAllocEx(g.h,None,8,0x3000,0x04); g.wpm(itp,b"\0"*8)
    while True:
        m=g.rc(F["il2cpp_class_get_methods"],cls,itp)
        if not m: break
        if rcstr(g.rc(F["il2cpp_method_get_name"],m))!=name: continue
        if g.rc(F["il2cpp_method_get_param_count"],m)!=len(ptypes): continue
        if all(ptypes[i] in (rcstr(g.rc(F["il2cpp_type_get_name"],g.rc(F["il2cpp_method_get_param"],m,i))) or "") for i in range(len(ptypes))):
            return g.rptr(m), m
    return 0,0
def pack_v2(x,y): return struct.unpack("<Q",struct.pack("<ff",float(x),float(y)))[0]
def fb(v): return struct.unpack("<I",struct.pack("<f",float(v)))[0]
def v2(p): return (g.rf32(p+0),g.rf32(p+4))
def storedLocal(val): loc=g.rptr(val+0x60); return v2(loc+0x78) if loc else None

# --- trampolines ---
# 5-arg (this+3+mi) for UpdateLine
T5=bytes([0x48,0x89,0xC8,0x4C,0x8B,0x10,0x48,0x8B,0x48,0x08,0x48,0x8B,0x50,0x10,0x4C,0x8B,0x40,0x18,0x4C,0x8B,0x48,0x20,0x4C,0x8B,0x58,0x28,0x48,0x83,0xEC,0x28,0x4C,0x89,0x5C,0x24,0x20,0x41,0xFF,0xD2,0x48,0x83,0xC4,0x28,0xC3])
t5=G.VirtualAllocEx(g.h,None,len(T5),0x3000,0x40); g.wpm(t5,T5); b5=G.VirtualAllocEx(g.h,None,0x40,0x3000,4)
def call5(c,a0,a1,a2,a3,a4):
    M=(1<<64)-1; g.wpm(b5,struct.pack("<6Q",c,a0&M,a1&M,a2&M,a3&M,a4&M)); g.main_call(t5,b5)
# 6-arg with XMM for grid converter (float args)
T6=bytes([0x48,0x89,0xC8,0x48,0x8B,0x48,0x08,0x48,0x8B,0x50,0x10,0x4C,0x8B,0x40,0x18,0x4C,0x8B,0x48,0x20,
 0xF3,0x0F,0x7E,0x40,0x08,0xF3,0x0F,0x7E,0x48,0x10,0xF3,0x0F,0x7E,0x50,0x18,0xF3,0x0F,0x7E,0x58,0x20,
 0x4C,0x8B,0x50,0x28,0x4C,0x8B,0x58,0x30,0x48,0x8B,0x00,0x48,0x83,0xEC,0x38,0x4C,0x89,0x54,0x24,0x20,0x4C,0x89,0x5C,0x24,0x28,0xFF,0xD0,0x48,0x83,0xC4,0x38,0xC3])
t6=G.VirtualAllocEx(g.h,None,len(T6),0x3000,0x40); g.wpm(t6,T6); b6=G.VirtualAllocEx(g.h,None,0x40,0x3000,4)
def call6(c,a0,a1,a2,a3,a4,a5):
    M=(1<<64)-1; g.wpm(b6,struct.pack("<7Q",c,a0&M,a1&M,a2&M,a3&M,a4&M,a5&M)); return g.main_call(t6,b6)[0]

go_cls=g.get_class("GameObject","UnityEngine",g.core); comp_cls=g.get_class("Component","UnityEngine",g.core)
tr_cls=g.get_class("Transform","UnityEngine",g.core); obj_cls=g.get_class("Object","UnityEngine",g.core)
line_cls=g.get_class("MapMarkerLineUI"); gc_cls=g.get_class("GridCodeConverter")
m_tr=meth(comp_cls,"get_transform",0); m_par=meth(tr_cls,"get_parent",0); m_go=meth(comp_cls,"get_gameObject",0)
m_setlpos=meth(tr_cls,"set_localPosition",1); m_setEuler=meth(tr_cls,"set_localEulerAngles",1)
m_gcic=find_method(go_cls,"GetComponentInChildren",["Type","Boolean"]); m_inst=find_method(obj_cls,"Instantiate",["Object","Transform","Boolean"])
m_init=meth(line_cls,"Initialize",2); m_upd=meth(line_cls,"UpdateLine",3); m_lbl=meth(line_cls,"SetLabelsVisible",1)
m_spd=meth(line_cls,"SetNormalizedSpeed",2)
m_destroy=find_method(obj_cls,"Destroy",["Object"])
m_l2c=meth(gc_cls,"LocalToCode",5); m_c2l=meth(gc_cls,"CodeToLocal",4)
def tr_of(c): return g.main_call(m_tr[0],c,m_tr[1])[0]
def typeobj(cls):
    ty=g.rc(F["il2cpp_class_get_type"],cls); return g.rc(F["il2cpp_type_get_object"],ty)
def setvec3(m,t,x,y,z):
    vec=G.VirtualAllocEx(g.h,None,16,0x3000,0x04); g.wpm(vec,struct.pack("<fff",x,y,z)); g.main_call(m[0],t,vec,m[1])

fm=g.find_one("FireMission"); CW=g.rf32(fm+0x38); CH=g.rf32(fm+0x3c); YUP=g.rb(fm+0x40)
def code_to_local(code):
    s=g.main_call(F["il2cpp_string_new"], g.cstr(380,code))[0]
    packed=call6(m_c2l[0], s, fb(CW), fb(CH), YUP, m_c2l[1], 0)
    return struct.unpack("<ff", struct.pack("<Q", packed&0xffffffffffffffff))
def local_to_code(x,y):
    return rstr(call6(m_l2c[0], pack_v2(x,y), fb(CW), fb(CH), YUP, 0, m_l2c[1]))

import re as _re
def _tptext(p,m=4000):
    if not p: return ""
    n=g.ru32(p+0x10); n=min(max(n,0),m); return g.rpm(p+0x14,n*2).decode("utf-16-le","ignore") if n else ""
def read_player_code():
    for tp in g.find_objects("Teleprinter"):
        txt=_re.sub(r"<[^>]+>","",_tptext(g.rptr(g.rptr(tp+0x100)+0xe0)))
        mm=_re.search(r"IRON\s*NEST\s*[-:]?\s*([A-Z]\s*\d{1,2}\s*\d:\d)", txt, _re.I)
        if mm: return _re.sub(r"\s+"," ",mm.group(1)).strip()
    return None
if PLAYER_CODE is None:
    PLAYER_CODE=read_player_code()
    if not PLAYER_CODE: print("could not read IRON NEST position from teleprinter"); sys.exit()
    print("read player position from 'Orders' teleprinter: IRON NEST -> %s"%PLAYER_CODE)
if not g.find_objects("MapMarkerPlacer") or (g.rf32(fm+0x38) or 0) <= 0:
    print("MAP IS CLOSED (no MapMarkerPlacer / grid cell size = 0) -> open the in-game map first.");
    print("Aborting BEFORE any grid-converter call to avoid crashing the game."); sys.exit()
player=code_to_local(PLAYER_CODE)
print("PLAYER grid %s -> local=(%.3f,%.3f)"%(PLAYER_CODE, player[0],player[1]))

placer=g.find_objects("MapMarkerPlacer")[0]; prefab=g.rptr(placer+0x30); mapRect=g.rptr(placer+0x80)
# clean slate: clear placer.placedMarkers (avoid dead refs) then destroy all existing lines
LGO=r"C:\Users\Owner\AppData\Local\Temp\claude\C--Users-Owner\776c532f-07d9-4785-9015-6eaac32a484e\scratchpad\_line_go.txt"
existing=g.find_objects("MapMarkerLineUI")
g.wpm(g.rptr(placer+0x88)+0x18, struct.pack("<i",0))    # placedMarkers count = 0
for L in existing:
    go=g.main_call(m_go[0],L,m_go[1])[0]
    if go: g.main_call(m_destroy[0], go, m_destroy[1])
print("cleared %d existing line(s) for a clean slate"%len(existing))
# target = nearest HOSTILE entity (handles hostiletank / hostileinfatry / hostilebunker / ...)
d=g.rptr(fm+0x78); entries=g.rptr(d+0x18); cnt=g.ru32(d+0x20); ents={}; byname={}
for i in range(cnt):
    val=g.rptr(entries+0x20+i*0x18+0x10)
    if val:
        ents[rstr(g.rptr(val+0x10))]=val          # key by ID  (e.g. 'target1', 'hostiletank1')
        byname[rstr(g.rptr(val+0x18))]=val         # key by Name (e.g. 'AmmoCache#1')
if TARGET and TARGET.upper()=="RANDOM":
    while True:   # random reachable grid point (3-7km from the gun, inside the grid)
        R=random.uniform(3.0,7.0); B=math.radians(random.uniform(10,140))
        tx=player[0]+R*math.sin(B); ty=player[1]+R*math.cos(B)
        if 0.6<=tx<=17.4 and 0.6<=ty<=8.4: break
    tl=(tx,ty); TARGET="RANDOM %s"%local_to_code(tx,ty)
elif TARGET and TARGET.upper() in ("RANDOMENEMY","RANDENEMY","ENEMY"):
    def _rng(sl): return math.hypot(sl[0]-player[0],sl[1]-player[1])
    def _alive(nm): return struct.unpack("<i", g.rpm(ents[nm]+0x68,4) or b"\0\0\0\0")[0] > 0
    cands=[]
    for nm in ents:
        if "hostile" not in nm: continue
        sl=storedLocal(ents[nm])
        if sl and _alive(nm) and _rng(sl)<=25.0: cands.append((nm,sl))
    if not cands: print("no LIVE hostile in range (<=25km)"); sys.exit()
    TARGET,tl=random.choice(cands)
    print("RANDOM ENEMY -> %s (range %.2f km)"%(TARGET,_rng(tl)))
elif TARGET and TARGET.upper() in ("ARTILLERY","ARTY"):
    # select a LIVE enemy artillery on the fly by ICON (no hardcoded name). IRN_EXCLUDE=ids to skip (prefer unseen).
    _excl=set(x for x in (os.environ.get("IRN_EXCLUDE","") or "").split(",") if x)
    def _rng(sl): return math.hypot(sl[0]-player[0],sl[1]-player[1])
    def _alive(v): return struct.unpack("<i", g.rpm(v+0x68,4) or b"\0\0\0\0")[0] > 0
    cands=[]
    for nm,val in ents.items():
        ic=rstr(g.rptr(val+0x20))
        if "field artillery" in ic.lower() and "observer" not in ic.lower():   # the guns, not the observers
            sl=storedLocal(val)
            if sl and _alive(val) and _rng(sl)<=15.0: cands.append((nm,sl))
    if not cands: print("ARTILLERY: no live artillery in range (<=15km)"); sys.exit()
    fresh=[c for c in cands if c[0] not in _excl]
    TARGET,tl=min((fresh or cands), key=lambda c: _rng(c[1]))   # NEAREST artillery, preferring unseen ones
    print("ARTILLERY -> %s (range %.2f km; %d live, %d unseen)"%(TARGET,_rng(tl),len(cands),len(fresh)))
elif TARGET:
    tv=ents.get(TARGET) or byname.get(TARGET)
    if not tv: print("target %r not found; IDs=%s names=%s"%(TARGET,list(ents)[:8],list(byname)[:8])); sys.exit()
    tl=storedLocal(tv)
else:
    def _rng(sl): return math.hypot(sl[0]-player[0],sl[1]-player[1])
    def _alive(nm): return struct.unpack("<i", g.rpm(ents[nm]+0x68,4))[0] > 0   # Health>0
    hostiles=[(nm,storedLocal(ents[nm])) for nm in ents if "hostile" in nm and storedLocal(ents[nm]) and _alive(nm)]
    if not hostiles:
        print("no LIVE hostile entity found"); raise SystemExit("no live hostile target")
    tanks=[t for t in hostiles if "hostiletank" in t[0] and _rng(t[1])<=9.0]
    TARGET,tl=min(tanks if tanks else hostiles, key=lambda t: _rng(t[1]))
print("TARGET %s -> local=(%.2f,%.2f) grid=%s"%(TARGET,tl[0],tl[1],local_to_code(*tl)))
# shell picker: target Icon containing "Cache" -> AP, everything else -> HE
SHELL="HE"
_tv = (ents.get(TARGET) or byname.get(TARGET)) if not (TARGET or "").startswith("RANDOM") else None
_icon = rstr(g.rptr(_tv+0x20)) if _tv else "(random point)"
_name = rstr(g.rptr(_tv+0x18)) if _tv else ""
if _tv and ("Frendly" in _icon or "Friendly" in _icon or "Ally" in _icon or _name.lower().startswith("ally")):
    print("  !! %r is FRIENDLY (Icon=%r) -> ABORTING, will not fire on friendlies"%(TARGET,_icon)); sys.exit()
if _tv and any(k in (_name+" "+_icon) for k in ("Cache","Tank","Armor","Bunker","FDC","Fire Direction")): SHELL="AP"
print("  shell picker: Icon=%r Name=%r -> %s (AP=armored Tank/Cache/Bunker/FDC, HE=soft infantry/artillery)"%(_icon, _name, SHELL))

parent=mapRect   # the line's direct parent (its GameObject is named 'MapMarkers'); exists from mission start
newGO=g.main_call(m_inst[0], prefab, parent, 0, m_inst[1])[0]
try:
    g.main_call(meth(go_cls,"SetActive",1)[0], newGO, 1, meth(go_cls,"SetActive",1)[1])
    MUI=g.main_call(m_gcic[0], newGO, typeobj(line_cls), 1, m_gcic[1])[0]; t=tr_of(MUI)
    if not MUI or not t: raise RuntimeError("component/transform null")
    setvec3(m_setEuler,t,0.0,0.0,0.0); setvec3(m_setlpos,t,player[0],player[1],0.0)
    g.main_call(m_init[0], MUI, pack_v2(*player), mapRect, m_init[1])
    call5(m_upd[0], MUI, pack_v2(*player), pack_v2(*tl), mapRect, m_upd[1])
    g.main_call(m_spd[0], MUI, 0, 0, m_spd[1]); g.wf32(MUI+0xf8, 0.0)   # reset marker speed -> stop the looping draw sound
    g.main_call(m_lbl[0], MUI, 1, m_lbl[1]); g.wbool(MUI+0x10d, False)
    plist=g.rptr(placer+0x88); lk=g.rptr(plist); add_mi=g.rc(F["il2cpp_class_get_method_from_name"], lk, g.cstr(320,"Add"), 1)
    g.main_call(g.rptr(add_mi), plist, newGO, add_mi)
except Exception as e:
    g.main_call(m_destroy[0], newGO, m_destroy[1])   # never leave a half-built orphan line
    print("setup failed (%s) -> destroyed orphan, no crash"%e); raise
time.sleep(0.3)
def tmptext(p): return rstr(g.rptr(p+0xe0)) if p else ""
print("\n=== LINE: player(%s) -> %s ==="%(PLAYER_CODE,TARGET))
print("  origin=(%.3f,%.3f)  BEARING=%.2f [%s]  RANGE=%.2f [%s]"%(
    g.rf32(MUI+0xe0),g.rf32(MUI+0xe4),g.rf32(MUI+0xd8),tmptext(g.rptr(MUI+0x80)),g.rf32(MUI+0xdc),tmptext(g.rptr(MUI+0x88))))
open(LGO,"w").write("%d %d %d"%(newGO, placer, g.pid))
open(LGO.replace("_line_go.txt","_shot.txt"),"w").write("%.2f %.2f %s"%(g.rf32(MUI+0xd8), g.rf32(MUI+0xdc), SHELL))
# write target ENTITY name for impact spotting ("" if random point, no entity)
_te = "" if (TARGET or "").startswith("RANDOM") else (TARGET or "")
open(LGO.replace("_line_go.txt","_target.txt"),"w").write(_te)
print("  (wrote bearing/range to _shot.txt for the fire-mission step)")
