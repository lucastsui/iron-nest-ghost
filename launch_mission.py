"""Launch an IRON NEST mission directly via IL2CPP (no screen clicks).

Installs a 5-byte rel32 trampoline on MissionManager.Update (its first 5 bytes are
one clean, position-independent instruction `mov [rsp+0x20],rbx`), so coroutine /
scene-loading methods run on Unity's main thread. MissionManager ticks at the menu,
so this works from the main menu (unlike TurretController.Update).

Usage:
  python launch_mission.py map                  # EnterBrowsingMap() == press PLAY
  python launch_mission.py mission <substr>     # LoadMission(MissionGraph matching substr)
  python launch_mission.py chill                # LoadMission(MissionGraph_Chill)  [the sandbox]
  python launch_mission.py menu                 # LoadMainMenu()
"""
import os, sys, struct, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ironnest_ghost as G
from ironnest_ghost import Ghost, DLL, export_rvas, _build_dispatch, _le64

g = Ghost(); g._build_images(); F = g.F
rvas = export_rvas(DLL)
for n in ("il2cpp_class_get_method_from_name","il2cpp_runtime_class_init",
          "il2cpp_class_get_field_from_name","il2cpp_field_static_get_value",
          "il2cpp_class_get_type","il2cpp_type_get_object"):
    if n in rvas and n not in F: F[n] = g.base + rvas[n]
CORE = g.core
MEM_COMMIT_RESERVE = 0x3000
PAGE_RWX = 0x40

def klass(name, ns="", image=None): return g.get_class(name, ns, image)
def read_str(p):
    if not p: return ""
    ln = g.ru32(p + 0x10)
    if ln <= 0 or ln > 512: return ""
    raw = g.rpm(p + 0x14, ln*2)
    return raw.decode('utf-16-le','ignore') if raw else ""

# ---- MissionManager singleton ----
MM = klass("MissionManager"); g.rc(F["il2cpp_runtime_class_init"], MM)
fld = g.rc(F["il2cpp_class_get_field_from_name"], MM, g.cstr(64, "<Instance>k__BackingField"))
ob = g.scr + 256; g.wpm(ob, b"\0"*8); g.rc(F["il2cpp_field_static_get_value"], fld, ob)
MM_INST = g.rptr(ob)
if not MM_INST: raise SystemExit("MissionManager.Instance is null")
def phase(): return g.ru32(MM_INST + 0x20)
def mptr(name, argc):
    mi = g.rc(F["il2cpp_class_get_method_from_name"], MM, g.cstr(320, name), argc)
    return g.rptr(mi)

# ---- 5-byte rel32 executor on MissionManager.Update ----
class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),
                ("AllocationProtect",G.wt.DWORD),("__a1",G.wt.DWORD),
                ("RegionSize",ctypes.c_size_t),("State",G.wt.DWORD),
                ("Protect",G.wt.DWORD),("Type",G.wt.DWORD),("__a2",G.wt.DWORD)]
_VirtualQueryEx = G.k32.VirtualQueryEx
_VirtualQueryEx.restype = ctypes.c_size_t
_VirtualQueryEx.argtypes = [G.wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]

def alloc_near(target, size):
    GRAN = 0x10000; MEM_FREE = 0x10000; RANGE = 0x7f000000
    # fast path: a few hints
    for delta in (0x2000000,-0x2000000,0x8000000,-0x8000000,0x10000000,-0x10000000):
        hint = (target + delta) & ~(GRAN-1)
        a = G.VirtualAllocEx(g.h, ctypes.c_void_p(hint), size, MEM_COMMIT_RESERVE, PAGE_RWX)
        if a and abs(a - target) < RANGE: return a
    # robust path: scan free regions within +/-2GB via VirtualQueryEx
    addr = max(GRAN, target - RANGE) & ~(GRAN-1)
    hi = target + RANGE
    mbi = _MBI()
    while addr < hi:
        if _VirtualQueryEx(g.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            addr += GRAN; continue
        base = mbi.BaseAddress or addr; rsize = mbi.RegionSize or GRAN
        if mbi.State == MEM_FREE and rsize >= size:
            cand = (base + GRAN - 1) & ~(GRAN-1)
            if cand + size <= base + rsize and abs(cand - target) < RANGE:
                a = G.VirtualAllocEx(g.h, ctypes.c_void_p(cand), size, MEM_COMMIT_RESERVE, PAGE_RWX)
                if a and abs(a - target) < RANGE: return a
        addr = base + rsize
    return 0

def install_exec():
    if getattr(g, "cmd", None): return
    upd = mptr("Update", 0)
    pro5 = g.rpm(upd, 5)
    if pro5 != b"\x48\x89\x5c\x24\x20":
        raise SystemExit(f"unexpected MissionManager.Update prologue {pro5.hex(' ')}; not safe to 5-byte hook")
    g._upd = upd; g._orig5 = pro5
    g.cmd = G.VirtualAllocEx(g.h, None, 0x80, MEM_COMMIT_RESERVE, 0x04)
    g.wpm(g.cmd, b"\0"*0x80)
    disp = _build_dispatch(g.cmd)                       # position-independent
    cave_size = len(disp) + 5 + 5 + 16
    cave = alloc_near(upd, cave_size)
    if not cave: raise SystemExit("could not allocate cave within rel32 range")
    g.cave = cave
    jmpback_at = cave + len(disp) + 5                   # after disp + stolen5
    rel_back = (upd + 5) - (jmpback_at + 5)
    cave_code = disp + g._orig5 + b"\xE9" + struct.pack("<i", rel_back)
    g.wpm(cave, cave_code)
    rel_to_cave = cave - (upd + 5)
    hook = b"\xE9" + struct.pack("<i", rel_to_cave)
    old = G.wt.DWORD(0)
    G.VirtualProtectEx(g.h, ctypes.c_void_p(upd), 5, PAGE_RWX, ctypes.byref(old))
    g.wpm(upd, hook)
    G.VirtualProtectEx(g.h, ctypes.c_void_p(upd), 5, old.value, ctypes.byref(old))
    print(f"[exec] hooked MissionManager.Update@0x{upd:x} -> cave 0x{cave:x} (cmd 0x{g.cmd:x})")

def uninstall_exec():
    if getattr(g, "_orig5", None) and getattr(g, "_upd", None):
        # clear any pending command, let a frame pass, then restore
        g.wpm(g.cmd, struct.pack("<Q", 0)); time.sleep(0.1)
        old = G.wt.DWORD(0)
        G.VirtualProtectEx(g.h, ctypes.c_void_p(g._upd), 5, PAGE_RWX, ctypes.byref(old))
        g.wpm(g._upd, g._orig5)
        G.VirtualProtectEx(g.h, ctypes.c_void_p(g._upd), 5, old.value, ctypes.byref(old))
        # free remote allocations so repeated runs don't leak cave/cmd in the game
        time.sleep(0.08)   # let any in-flight frame exit the cave before releasing it
        MEM_RELEASE = 0x8000
        for a in (getattr(g, "cave", 0), getattr(g, "cmd", 0)):
            if a: G.k32.VirtualFreeEx(g.h, ctypes.c_void_p(a), 0, MEM_RELEASE)
        g.cmd = None
        print("[exec] uninstalled")

# ---- asset enumeration (read-only, via mcall) ----
def setup_find():
    objcls = klass("Object","UnityEngine",CORE)
    g._mi_findall = g.rc(F["il2cpp_class_get_method_from_name"], klass("Resources","UnityEngine",CORE), g.cstr(320,"FindObjectsOfTypeAll"),1)
    g._m_findall = g.rptr(g._mi_findall)
    g._mi_getname = g.rc(F["il2cpp_class_get_method_from_name"], objcls, g.cstr(320,"get_name"),0)
    g._m_getname = g.rptr(g._mi_getname)
def find_all(clsname, ns=""):
    kl = klass(clsname, ns)
    if not kl: return []
    g.rc(F["il2cpp_runtime_class_init"], kl)
    ty = g.rc(F["il2cpp_class_get_type"], kl); tyobj = g.rc(F["il2cpp_type_get_object"], ty)
    res = g.mcall(g._m_findall, tyobj, g._mi_findall)
    if not res: return []
    n = g.rptr(res + 0x18)
    return [g.rptr(res+0x20+k*8) for k in range(min(n,256)) if g.rptr(res+0x20+k*8)]
def obj_name(o): return read_str(g.mcall(g._m_getname, o, g._mi_getname))

cmd = sys.argv[1] if len(sys.argv) > 1 else "map"
print(f"phase before = {phase()}")
g.focus_game()
install_exec()

try:
    if cmd == "map":
        ptr = mptr("EnterBrowsingMap", 0)
        print(f"call EnterBrowsingMap ptr=0x{ptr:x}")
        print("  ret =", g.main_call(ptr, MM_INST))
        target_phase = 1
    elif cmd == "menu":
        ptr = mptr("LoadMainMenu", 0)
        print("  ret =", g.main_call(ptr, MM_INST)); target_phase = 0
    elif cmd == "startop":
        op_sub = sys.argv[2] if len(sys.argv) > 2 else "Tutorial"
        mi_sub = sys.argv[3] if len(sys.argv) > 3 else "Chill"
        setup_find()
        ops = [(o, obj_name(o)) for o in find_all("OperationGraph","SleepyNodes")]
        mis = [(m, obj_name(m)) for m in find_all("MissionGraph","SleepyNodes")]
        print("operations:", [n for _,n in ops]); print("missions:", [n for _,n in mis])
        op = next((o for o,n in ops if op_sub.lower() in n.lower()), 0)
        ms = next((m for m,n in mis if mi_sub.lower() in n.lower()), 0)
        if not op or not ms: raise SystemExit(f"no match op='{op_sub}' mission='{mi_sub}'")
        print(f"StartOperation(op=0x{op:x} '{obj_name(op)}', mission=0x{ms:x} '{obj_name(ms)}')")
        ptr = mptr("StartOperation", 2)
        print(f"call StartOperation ptr=0x{ptr:x}")
        print("  ret =", g.main_call(ptr, MM_INST, op, ms))
        target_phase = 2
    else:
        substr = "Chill" if cmd == "chill" else (sys.argv[2] if len(sys.argv) > 2 else "Chill")
        setup_find()
        mis = find_all("MissionGraph","SleepyNodes")
        names = [(m, obj_name(m)) for m in mis]
        print("missions:", [n for _,n in names])
        ms = next((m for m,n in names if substr.lower() in n.lower()), 0)
        if not ms: raise SystemExit(f"no MissionGraph matching '{substr}'")
        print(f"LoadMission target = 0x{ms:x} ('{obj_name(ms)}')")
        ptr = mptr("LoadMission", 2)
        print(f"call LoadMission ptr=0x{ptr:x}")
        print("  ret =", g.main_call(ptr, MM_INST, ms, 0))
        target_phase = 2

    for _ in range(80):
        time.sleep(0.25)
        if phase() == target_phase: break
    print(f"phase after = {phase()}  (target {target_phase})  scene='{read_str(g.rptr(MM_INST+0x40))}'")
finally:
    uninstall_exec()
