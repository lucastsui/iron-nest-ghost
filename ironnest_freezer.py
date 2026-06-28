import ctypes, ctypes.wintypes as wt, struct, sys, time, os

DLL = r"C:\Program Files (x86)\Steam\steamapps\common\IRON NEST Heavy Turret Simulator Demo\GameAssembly.dll"  # fallback only; auto-detected from the running game below
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

def cksum(real, key):
    # ProtectedInt.CalculateChecksum, reverse-engineered from GameAssembly.dll:
    # ((real*31 + key)*31 + 0x5A1F8422), 32-bit wraparound.
    t = (real * 31) & 0xffffffff
    t = (t + key)   & 0xffffffff
    t = (t * 31)    & 0xffffffff
    t = (t + 0x5A1F8422) & 0xffffffff
    return t

# ---- find process + module base via toolhelp ----
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
    ok=Process32First(snap,ctypes.byref(e))
    pid=None
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

# ---- export RVAs from the dll file ----
def export_rvas(path):
    d=open(path,"rb").read()
    e=struct.unpack_from("<I",d,0x3C)[0]; opt=e+4+20
    magic,=struct.unpack_from("<H",d,opt)
    dd=opt+(112 if magic==0x20b else 96)
    expva,_=struct.unpack_from("<II",d,dd)
    # section map
    nsec,=struct.unpack_from("<H",d,e+4+2); optsz,=struct.unpack_from("<H",d,e+4+16)
    secs=[]
    so=opt+optsz
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
    foff=v2o(aF); noff=v2o(aN); ooff=v2o(aO)
    out={}
    for i in range(nN):
        nrva,=struct.unpack_from("<I",d,noff+i*4); o=v2o(nrva)
        end=d.index(b'\0',o); nm=d[o:end].decode()
        ordi,=struct.unpack_from("<H",d,ooff+i*2)
        frva,=struct.unpack_from("<I",d,foff+ordi*4)
        out[nm]=frva
    return out

def main():
    log("waiting for game process...")
    pid=None
    for _ in range(600):
        pid=find_pid()
        if pid: break
        time.sleep(1)
    if not pid:
        log("RESULT: game process not found after wait."); return
    log(f"[ok] process pid={pid}")
    h=OpenProcess(PROCESS_ALL,False,pid)
    if not h: log("ERROR: OpenProcess failed", ctypes.get_last_error()); return
    base=module_base(pid)
    log(f"[ok] GameAssembly.dll base=0x{base:x}")
    rvas=export_rvas(DLL)
    F={n:base+rvas[n] for n in [
        "il2cpp_domain_get","il2cpp_domain_get_assemblies","il2cpp_assembly_get_image",
        "il2cpp_image_get_name","il2cpp_class_from_name","il2cpp_class_get_field_from_name",
        "il2cpp_field_static_get_value","il2cpp_field_get_offset","il2cpp_runtime_class_init",
        "il2cpp_class_get_method_from_name"]}

    def rpm(addr,size):
        buf=(ctypes.c_char*size)(); n=ctypes.c_size_t(0)
        ok=ReadProcessMemory(h,ctypes.c_void_p(addr),buf,size,ctypes.byref(n))
        return bytes(buf[:n.value]) if ok else None
    def wpm(addr,data):
        n=ctypes.c_size_t(0); b=(ctypes.c_char*len(data))(*data)
        return WriteProcessMemory(h,ctypes.c_void_p(addr),b,len(data),ctypes.byref(n))
    def rptr(a): r=rpm(a,8); return struct.unpack("<Q",r)[0] if r else 0
    def ru32(a): r=rpm(a,4); return struct.unpack("<I",r)[0] if r else 0
    def rf32(a): r=rpm(a,4); return struct.unpack("<f",r)[0] if r else None
    def rcstr(a,m=128):
        r=rpm(a,m);
        if not r: return ""
        z=r.find(b'\0'); return r[:z if z>=0 else m].decode(errors="ignore")

    # remote-call stub (x64): rcx=block[func,a0,a1,a2,a3,ret]
    stub=bytes([
        0x53,                                # push rbx
        0x48,0x89,0xCB,                      # mov rbx,rcx
        0x48,0x8B,0x03,                      # mov rax,[rbx]
        0x48,0x8B,0x4B,0x08,                 # mov rcx,[rbx+8]
        0x48,0x8B,0x53,0x10,                 # mov rdx,[rbx+16]
        0x4C,0x8B,0x43,0x18,                 # mov r8,[rbx+24]
        0x4C,0x8B,0x4B,0x20,                 # mov r9,[rbx+32]
        0x48,0x83,0xEC,0x20,                 # sub rsp,0x20
        0xFF,0xD0,                           # call rax
        0x48,0x83,0xC4,0x20,                 # add rsp,0x20
        0x48,0x89,0x43,0x28,                 # mov [rbx+40],rax
        0x5B,                                # pop rbx
        0xC3])                               # ret
    MEM_COMMIT=0x3000
    stub_addr=VirtualAllocEx(h,None,len(stub),MEM_COMMIT,0x40)
    blk=VirtualAllocEx(h,None,0x60,MEM_COMMIT,0x04)
    scratch=VirtualAllocEx(h,None,0x400,MEM_COMMIT,0x04)
    wpm(stub_addr,stub)
    log(f"[ok] stub=0x{stub_addr:x} block=0x{blk:x} scratch=0x{scratch:x}")

    def rc(func,*args):
        a=list(args)+[0]*(4-len(args))
        wpm(blk,struct.pack("<6Q",func,a[0],a[1],a[2],a[3],0))
        th=CreateRemoteThread(h,None,0,ctypes.c_void_p(stub_addr),ctypes.c_void_p(blk),0,None)
        if not th: log("  ERROR CreateRemoteThread",ctypes.get_last_error()); return 0
        WaitForSingleObject(th,5000); CloseHandle(th)
        return rptr(blk+40)

    # scratch layout
    NS=scratch+0;        wpm(NS,b"\0")
    CBT=scratch+16;      wpm(CBT,b"CounterBatteryTimer\0")
    MST=scratch+64;      wpm(MST,b"MissionStatsTracker\0")
    FLD_INST_T=scratch+128; wpm(FLD_INST_T,b"<Instance>k__BackingField\0")
    FLD_INST_S=scratch+192; wpm(FLD_INST_S,b"Instance\0")
    FLD_REM=scratch+208; wpm(FLD_REM,b"_remainingSeconds\0")
    FLD_RP=scratch+240;  wpm(FLD_RP,b"requisitionPoints\0")
    M_SET=scratch+352;   wpm(M_SET,b"SetRequisitionPoints\0")
    OUTB=scratch+288     # out buffer
    SZP=scratch+320      # size_t for assemblies

    log("\n--- resolving via IL2CPP API ---")
    dom=rc(F["il2cpp_domain_get"]); log(f"domain=0x{dom:x}")
    if not dom: log("RESULT: il2cpp not ready (is the game past the menu/in a mission?)"); return
    arr=rc(F["il2cpp_domain_get_assemblies"],dom,SZP); cnt=rptr(SZP)
    log(f"assemblies array=0x{arr:x} count={cnt}")
    image=0
    for i in range(min(cnt,200)):
        asm=rptr(arr+i*8)
        if not asm: continue
        img=rc(F["il2cpp_assembly_get_image"],asm)
        nm=rcstr(rc(F["il2cpp_image_get_name"],img))
        if nm=="Assembly-CSharp.dll": image=img; log(f"[ok] image '{nm}'=0x{img:x}"); break
    if not image: log("RESULT: Assembly-CSharp image not found"); return

    tC=rc(F["il2cpp_class_from_name"],image,NS,CBT); log(f"CounterBatteryTimer class=0x{tC:x}")
    sC=rc(F["il2cpp_class_from_name"],image,NS,MST); log(f"MissionStatsTracker class=0x{sC:x}")
    if not tC or not sC: log("RESULT: class resolve failed"); return
    rc(F["il2cpp_runtime_class_init"],tC); rc(F["il2cpp_runtime_class_init"],sC)

    # validate field offsets live vs static extraction
    def foff(klass,fldname_addr):
        fld=rc(F["il2cpp_class_get_field_from_name"],klass,fldname_addr)
        return fld, (rc(F["il2cpp_field_get_offset"],fld) if fld else 0)
    fRem,oRem=foff(tC,FLD_REM); log(f"_remainingSeconds field=0x{fRem:x} offset=0x{oRem:x} (expected 0x5c)")
    fRP,oRP=foff(sC,FLD_RP);    log(f"requisitionPoints field=0x{fRP:x} offset=0x{oRP:x} (expected 0x30)")

    # get singleton instances (wait for a mission to start)
    fT,_=foff(tC,FLD_INST_T)
    fS,_=foff(sC,FLD_INST_S)
    log("\nwaiting for a mission (singletons to spawn)...")
    tInst=sInst=0
    for _ in range(600):
        wpm(OUTB,b"\0"*8); rc(F["il2cpp_field_static_get_value"],fT,OUTB); tInst=rptr(OUTB)
        wpm(OUTB,b"\0"*8); rc(F["il2cpp_field_static_get_value"],fS,OUTB); sInst=rptr(OUTB)
        if tInst or sInst: break
        time.sleep(1)
    log(f"CounterBatteryTimer.Instance=0x{tInst:x}")
    log(f"MissionStatsTracker.Instance=0x{sInst:x}")
    if not tInst and not sInst:
        log("RESULT: singletons still null after wait."); return

    if tInst:
        rs=oRem or 0x5c
        log(f"timer _remainingSeconds = {rf32(tInst+rs)}  running={rpm(tInst+0x60,1)} expired={rpm(tInst+0x61,1)}")
    if sInst:
        rp=oRP or 0x30
        log(f"requisitionPoints(plain)=0x{rp:x} -> {ru32(sInst+rp)}")
        log(f"  encryptedValue={ru32(sInst+0x34)} key={ru32(sInst+0x38)} checksum={ru32(sInst+0x3c)} tamperFlag={rpm(sInst+0x44,1)}")

    # optional: set points high the SAFE way - pure memory writes (no game method calls).
    # encryptedValue = value XOR key (confirmed scheme); plain copy set too; flags cleared.
    if SET_POINTS is not None and sInst:
        key  = ru32(sInst+0x38)
        real = SET_POINTS & 0xffffffff
        enc  = (real ^ key) & 0xffffffff
        chk  = cksum(real, key)
        wpm(sInst+0x30, struct.pack("<I", real))   # requisitionPoints (plain copy)
        wpm(sInst+0x34, struct.pack("<I", enc))    # reqPoints.encryptedValue
        wpm(sInst+0x3c, struct.pack("<I", chk))    # reqPoints.checksum (VALID -> CheckTampered passes)
        time.sleep(0.05)
        log(f"\n[set] points -> {real}  enc={ru32(sInst+0x34)} key={key} "
            f"checksum={ru32(sInst+0x3c)} (computed valid={chk}) "
            f"WasTampered={rpm(sInst+0x41,1)} reqTamper={rpm(sInst+0x44,1)}")

    # ---- continuous freeze loop ----
    rs = oRem or 0x5c
    tTarget = rf32(tInst+rs) if tInst else None
    snap = rpm(sInst+0x30,16) if sInst else None
    log(f"\n--- FREEZING (Ctrl+C to stop). timer-hold={tTarget} points-snapshot-locked ---")
    i=0; reresolve=0
    while True:
        # re-resolve singletons periodically (new mission / scene reload)
        reresolve+=1
        if reresolve>=40:   # ~every 2s
            reresolve=0
            wpm(OUTB,b"\0"*8); rc(F["il2cpp_field_static_get_value"],fT,OUTB); nt=rptr(OUTB)
            wpm(OUTB,b"\0"*8); rc(F["il2cpp_field_static_get_value"],fS,OUTB); ns=rptr(OUTB)
            if nt and nt!=tInst: tInst=nt; tTarget=rf32(tInst+rs); log(f"[re] new timer inst 0x{tInst:x} hold={tTarget}")
            if ns and ns!=sInst: sInst=ns; snap=rpm(sInst+0x30,16); log(f"[re] new stats inst 0x{sInst:x}")
        if tInst and tTarget is not None: wpm(tInst+rs, struct.pack("<f",tTarget))
        if sInst and snap:
            wpm(sInst+0x30, snap)   # holds plain+enc+key+checksum, all self-consistent (no flag-clearing needed)
        if i % 40 == 0:   # log ~every 2s
            tv = rf32(tInst+rs) if tInst else None
            pv = ru32(sInst+(oRP or 0x30)) if sInst else None
            wt = rpm(sInst+0x41,1) if sInst else None   # reqPoints.WasTampered
            tf = rpm(sInst+0x44,1) if sInst else None   # requisitionPointsTampered
            log(f"  [{i*0.05:6.1f}s] timer={tv}  points={pv}  WasTampered={wt} reqTamper={tf}")
        i+=1
        if MAX_SECS and i*0.05>=MAX_SECS:
            log("\nRESULT: OK - ran to time limit, all functioned."); break
        time.sleep(0.05)

SET_POINTS=None   # e.g. 999999 to force a high amount via the game setter; None = freeze current
MAX_SECS=0        # 0 = run forever; >0 = stop after N seconds (used for testing)
if __name__=="__main__":
    for a in sys.argv[1:]:
        if a.startswith("set="):  SET_POINTS=int(a[4:])
        if a.startswith("secs="): MAX_SECS=float(a[5:])
    try: main()
    except KeyboardInterrupt: print("\n[stopped]")
    except Exception as e:
        import traceback; traceback.print_exc()
