import ctypes, ctypes.wintypes as wt, struct, sys, time, re

DLL = ""  # auto-detected from the running game's module list below
PROC_NAME = "Iron Nest Heavy Turret Simulator.exe"
MODNAME   = "GameAssembly.dll"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
def W(fn, res, *args):
    f = getattr(k32, fn); f.restype = res; f.argtypes = args; return f
OpenProcess        = W("OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
CloseHandle        = W("CloseHandle", wt.BOOL, wt.HANDLE)
ReadProcessMemory  = W("ReadProcessMemory", wt.BOOL, wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
WriteProcessMemory = W("WriteProcessMemory", wt.BOOL, wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
VirtualAllocEx     = W("VirtualAllocEx", ctypes.c_void_p, wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD)
CreateRemoteThread = W("CreateRemoteThread", wt.HANDLE, wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p)
WaitForSingleObject= W("WaitForSingleObject", wt.DWORD, wt.HANDLE, wt.DWORD)

def log(*a): print(*a, flush=True)

TH32_PROC=0x2; TH32_MODULE=0x8|0x10
class PE32(ctypes.Structure):
    _fields_=[("dwSize",wt.DWORD),("cnt",wt.DWORD),("th32ProcessID",wt.DWORD),
        ("d1",ctypes.c_void_p),("d2",wt.DWORD),("cntThreads",wt.DWORD),
        ("ppid",wt.DWORD),("pri",ctypes.c_long),("flags",wt.DWORD),("exe",ctypes.c_char*260)]
class ME32(ctypes.Structure):
    _fields_=[("dwSize",wt.DWORD),("mid",wt.DWORD),("pid",wt.DWORD),("glblcnt",wt.DWORD),
        ("proccnt",wt.DWORD),("base",ctypes.c_void_p),("size",wt.DWORD),
        ("hModule",ctypes.c_void_p),("mod",ctypes.c_char*256),("path",ctypes.c_char*260)]
CreateToolhelp32Snapshot=W("CreateToolhelp32Snapshot",wt.HANDLE,wt.DWORD,wt.DWORD)
Process32First=W("Process32First",wt.BOOL,wt.HANDLE,ctypes.POINTER(PE32))
Process32Next =W("Process32Next", wt.BOOL,wt.HANDLE,ctypes.POINTER(PE32))
Module32First =W("Module32First", wt.BOOL,wt.HANDLE,ctypes.POINTER(ME32))
Module32Next  =W("Module32Next",  wt.BOOL,wt.HANDLE,ctypes.POINTER(ME32))

def find_pid():
    snap=CreateToolhelp32Snapshot(TH32_PROC,0); e=PE32(); e.dwSize=ctypes.sizeof(PE32)
    ok=Process32First(snap,ctypes.byref(e)); pid=None
    while ok:
        if e.exe.decode(errors="ignore").lower()==PROC_NAME.lower(): pid=e.th32ProcessID; break
        ok=Process32Next(snap,ctypes.byref(e))
    CloseHandle(snap); return pid

def module_base(pid):
    snap=CreateToolhelp32Snapshot(TH32_MODULE,pid); m=ME32(); m.dwSize=ctypes.sizeof(ME32)
    ok=Module32First(snap,ctypes.byref(m)); base=None
    while ok:
        if m.mod.decode(errors="ignore").lower()==MODNAME.lower(): base=ctypes.cast(m.base,ctypes.c_void_p).value; break
        ok=Module32Next(snap,ctypes.byref(m))
    CloseHandle(snap); return base

def module_path(pid, modname=MODNAME):
    snap=CreateToolhelp32Snapshot(TH32_MODULE,pid); m=ME32(); m.dwSize=ctypes.sizeof(ME32)
    ok=Module32First(snap,ctypes.byref(m)); path=None
    while ok:
        if m.mod.decode(errors="ignore").lower()==modname.lower(): path=m.path.decode(errors="ignore"); break
        ok=Module32Next(snap,ctypes.byref(m))
    CloseHandle(snap); return path

def _autodetect_dll(fallback):
    try:
        pid=find_pid()
        if pid:
            p=module_path(pid)
            if p: return p
    except Exception: pass
    return fallback
DLL=_autodetect_dll(DLL)

def export_rvas(path):
    d=open(path,"rb").read()
    e=struct.unpack_from("<I",d,0x3C)[0]; opt=e+4+20
    magic,=struct.unpack_from("<H",d,opt)
    dd=opt+(112 if magic==0x20b else 96)
    expva,_=struct.unpack_from("<II",d,dd)
    nsec,=struct.unpack_from("<H",d,e+4+2); optsz,=struct.unpack_from("<H",d,e+4+16)
    secs=[]; so=opt+optsz
    for i in range(nsec):
        o=so+i*40; va,=struct.unpack_from("<I",d,o+12); raw,=struct.unpack_from("<I",d,o+20)
        vs,=struct.unpack_from("<I",d,o+8); rs,=struct.unpack_from("<I",d,o+16)
        secs.append((va,vs,raw,rs))
    def v2o(rva):
        for va,vs,raw,rs in secs:
            if va<=rva<va+max(vs,rs): return raw+(rva-va)
    eo=v2o(expva)
    nN,=struct.unpack_from("<I",d,eo+24); aF,=struct.unpack_from("<I",d,eo+28)
    aN,=struct.unpack_from("<I",d,eo+32); aO,=struct.unpack_from("<I",d,eo+36)
    foff=v2o(aF); noff=v2o(aN); ooff=v2o(aO); out={}
    for i in range(nN):
        nrva,=struct.unpack_from("<I",d,noff+i*4); o=v2o(nrva)
        end=d.index(b'\0',o); nm=d[o:end].decode()
        ordi,=struct.unpack_from("<H",d,ooff+i*2)
        frva,=struct.unpack_from("<I",d,foff+ordi*4)
        out[nm]=frva
    return out

# class-name keywords worth flagging
import os
_DEFAULT_KW=r"turret|aim|gun|barrel|wheel|knob|crank|hand|elevat|traverse|azimuth|pitch|yaw|rotat|control|player|recoil|gimbal|mount|sight|reticle|input|weapon|cannon|fire"
KW = re.compile(os.environ.get("IRN_KW", _DEFAULT_KW), re.I)

def main():
    pid=find_pid()
    if not pid: log("game not running"); return
    h=OpenProcess(PROCESS_ALL,False,pid)
    base=module_base(pid)
    log(f"[ok] pid={pid} base=0x{base:x}")
    rvas=export_rvas(DLL)
    need=["il2cpp_domain_get","il2cpp_domain_get_assemblies","il2cpp_assembly_get_image",
          "il2cpp_image_get_name","il2cpp_image_get_class_count","il2cpp_image_get_class",
          "il2cpp_class_get_name","il2cpp_class_get_namespace","il2cpp_class_get_fields",
          "il2cpp_field_get_name","il2cpp_field_get_offset","il2cpp_field_get_type",
          "il2cpp_type_get_name","il2cpp_class_get_methods","il2cpp_method_get_name",
          "il2cpp_method_get_param_count"]
    miss=[n for n in need if n not in rvas]
    if miss: log("missing exports:",miss)
    F={n:base+rvas[n] for n in need if n in rvas}

    def rpm(addr,size):
        buf=(ctypes.c_char*size)(); n=ctypes.c_size_t(0)
        ok=ReadProcessMemory(h,ctypes.c_void_p(addr),buf,size,ctypes.byref(n))
        return bytes(buf[:n.value]) if ok else None
    def wpm(addr,data):
        n=ctypes.c_size_t(0); b=(ctypes.c_char*len(data))(*data)
        return WriteProcessMemory(h,ctypes.c_void_p(addr),b,len(data),ctypes.byref(n))
    def rptr(a): r=rpm(a,8); return struct.unpack("<Q",r)[0] if r else 0
    def ru32(a): r=rpm(a,4); return struct.unpack("<I",r)[0] if r else 0
    def rcstr(a,m=256):
        if not a: return ""
        r=rpm(a,m)
        if not r: return ""
        z=r.find(b'\0'); return r[:z if z>=0 else m].decode(errors="ignore")

    stub=bytes([0x53,0x48,0x89,0xCB,0x48,0x8B,0x03,0x48,0x8B,0x4B,0x08,0x48,0x8B,0x53,0x10,
        0x4C,0x8B,0x43,0x18,0x4C,0x8B,0x4B,0x20,0x48,0x83,0xEC,0x20,0xFF,0xD0,
        0x48,0x83,0xC4,0x20,0x48,0x89,0x43,0x28,0x5B,0xC3])
    MEM_COMMIT=0x3000
    stub_addr=VirtualAllocEx(h,None,len(stub),MEM_COMMIT,0x40)
    blk=VirtualAllocEx(h,None,0x60,MEM_COMMIT,0x04)
    scratch=VirtualAllocEx(h,None,0x400,MEM_COMMIT,0x04)
    wpm(stub_addr,stub)

    def rc(func,*args):
        a=list(args)+[0]*(4-len(args))
        wpm(blk,struct.pack("<6Q",func,a[0],a[1],a[2],a[3],0))
        th=CreateRemoteThread(h,None,0,ctypes.c_void_p(stub_addr),ctypes.c_void_p(blk),0,None)
        if not th: return 0
        WaitForSingleObject(th,5000); CloseHandle(th)
        return rptr(blk+40)

    dom=rc(F["il2cpp_domain_get"])
    if not dom: log("il2cpp not ready (load into a mission first)"); return
    SZP=scratch+0; wpm(SZP,b"\0"*8)
    arr=rc(F["il2cpp_domain_get_assemblies"],dom,SZP); cnt=rptr(SZP)
    image=0
    for i in range(min(cnt,300)):
        asm=rptr(arr+i*8)
        if not asm: continue
        img=rc(F["il2cpp_assembly_get_image"],asm)
        if rcstr(rc(F["il2cpp_image_get_name"],img))=="Assembly-CSharp.dll": image=img; break
    if not image: log("Assembly-CSharp not found"); return
    n=rc(F["il2cpp_image_get_class_count"],image)
    log(f"[ok] Assembly-CSharp image=0x{image:x} classes={n}\n")

    want = [w.strip() for w in (sys.argv[1] if len(sys.argv)>1 else "").split(",") if w.strip()]
    hits=[]
    for i in range(n):
        kl=rc(F["il2cpp_image_get_class"],image,i)
        if not kl: continue
        nm=rcstr(rc(F["il2cpp_class_get_name"],kl))
        if KW.search(nm): hits.append((nm,kl))
    log(f"--- {len(hits)} candidate classes (keyword match) ---")
    for nm,kl in sorted(hits): log(f"  {nm}")

    # dump fields for any class whose name matches a CLI-provided substring
    if want:
        for nm,kl in sorted(hits):
            if not any(w.lower() in nm.lower() for w in want): continue
            log(f"\n==== {nm}  (class=0x{kl:x}) ====")
            itp=scratch+64; wpm(itp,b"\0"*8)
            while True:
                fld=rc(F["il2cpp_class_get_fields"],kl,itp)
                if not fld: break
                fn=rcstr(rc(F["il2cpp_field_get_name"],fld))
                off=rc(F["il2cpp_field_get_offset"],fld)
                ty=rc(F["il2cpp_field_get_type"],fld)
                tn=rcstr(rc(F["il2cpp_type_get_name"],ty)) if ty else "?"
                log(f"    +0x{off:<4x} {tn:<22} {fn}")
            mitp=scratch+128; wpm(mitp,b"\0"*8)
            log(f"    -- methods --")
            while True:
                m=rc(F["il2cpp_class_get_methods"],kl,mitp)
                if not m: break
                mn=rcstr(rc(F["il2cpp_method_get_name"],m))
                pc=rc(F["il2cpp_method_get_param_count"],m)
                log(f"       {mn}({pc})")

if __name__=="__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc()
