"""Read-only inspection of MissionManager: singleton, phase, method signatures.
Reuses ironnest_ghost.Ghost for attach + il2cpp resolution. Calls NOTHING that
mutates game state."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ironnest_ghost import Ghost, DLL, export_rvas

g = Ghost()
g._build_images()
F = g.F

# extra il2cpp exports for signature introspection
rvas = export_rvas(DLL)
for n in ("il2cpp_method_get_param_count","il2cpp_method_get_param",
          "il2cpp_method_get_param_name","il2cpp_type_get_name",
          "il2cpp_method_get_return_type","il2cpp_class_get_name",
          "il2cpp_field_static_get_value","il2cpp_class_get_field_from_name",
          "il2cpp_class_get_method_from_name","il2cpp_runtime_class_init"):
    if n in rvas:
        F[n] = g.base + rvas[n]

def cls(name, ns=""):
    return g.get_class(name, ns)

def get_method(klass, name, argc):
    m = g.rc(F["il2cpp_class_get_method_from_name"], klass, g.cstr(320, name), argc)
    return m  # MethodInfo*

def method_ptr(m):
    return g.rptr(m)  # native code pointer at offset 0

def sig(klass, name, argc):
    m = get_method(klass, name, argc)
    if not m:
        return f"{name}({argc}) -> NOT FOUND"
    pc = g.rc(F["il2cpp_method_get_param_count"], m)
    parts = []
    for i in range(pc):
        ty = g.rc(F["il2cpp_method_get_param"], m, i)
        tn = g.rcstr(g.rc(F["il2cpp_type_get_name"], ty)) if ty else "?"
        pn = g.rcstr(g.rc(F["il2cpp_method_get_param_name"], m, i)) if "il2cpp_method_get_param_name" in F else f"a{i}"
        parts.append(f"{tn} {pn}")
    rt = g.rc(F["il2cpp_method_get_return_type"], m) if "il2cpp_method_get_return_type" in F else 0
    rtn = g.rcstr(g.rc(F["il2cpp_type_get_name"], rt)) if rt else "void?"
    return f"{name}({', '.join(parts)}) -> {rtn}   [MethodInfo=0x{m:x} ptr=0x{method_ptr(m):x}]"

mm = cls("MissionManager")
print(f"[MissionManager class] = 0x{mm:x}")
g.rc(F["il2cpp_runtime_class_init"], mm)

# singleton via static backing field
fld = g.rc(F["il2cpp_class_get_field_from_name"], mm, g.cstr(64, "<Instance>k__BackingField"))
print(f"[<Instance> field] = 0x{fld:x}")
ob = g.scr + 256; g.wpm(ob, b"\0"*8)
g.rc(F["il2cpp_field_static_get_value"], fld, ob)
inst = g.rptr(ob)
print(f"[MissionManager.Instance] = 0x{inst:x}")
if inst:
    phase = g.ru32(inst + 0x20)
    name_str = g.rptr(inst + 0x40)  # CurrentMissionSceneName
    print(f"  CurrentPhase(+0x20) = {phase}  (0=MainMenu 1=BrowsingMap 2=MissionActive)")
    print(f"  CurrentMissionSceneName(+0x40 ptr) = 0x{name_str:x}")
    if name_str:
        # il2cpp string: length at +0x10, chars utf-16 at +0x14
        ln = g.ru32(name_str + 0x10)
        raw = g.rpm(name_str + 0x14, min(ln*2, 200))
        try: print("    sceneName =", raw.decode('utf-16-le', 'ignore'))
        except: pass

print("\n--- MissionManager method signatures ---")
for nm, ac in [("EnterBrowsingMap",0),("StartOperation",2),("LoadMission",2),
               ("SetPhase",1),("LoadMainMenu",0),("ReturnToMap",0),
               ("ReloadCurrentMission",0),("FinishMission",0)]:
    print("  ", sig(mm, nm, ac))
