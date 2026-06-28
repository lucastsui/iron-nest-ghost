"""
IRON NEST - "ghost" turret driver.

Drives the turret purely through game state, so the in-game handwheels/dials
backdrive and turn themselves. No screenshots, no synthetic mouse/keyboard.

Control model (reverse-engineered from TurretController / GunController):
  * TRAVERSE : isUsingSpeedDial=0, then write <DesiredRotation> (+0x128).
               The game's servo slews CurrentAngle (+0x12c) to it at
               maxManualRotationSpeed with real accel/decel; rotationDial backdrives.
  * ELEVATION: write each GunController.<DesiredElevationAngle> (+0xb8).
               Gun servo raises CurrentElevation (+0xb4); elevation dial backdrives.
  * FIRE     : remote-call TurretController.FireControlledGun().

IMPORTANT: the game pauses Update() when not focused, so nothing moves unless the
game window is the foreground app. focus_game() uses the AttachThreadInput trick
to force real activation.

Usage:
  python ironnest_ghost.py                  # read-only: print live state
  python ironnest_ghost.py rot=20           # slew to absolute bearing 20 deg
  python ironnest_ghost.py slew=+25         # slew +25 deg from current
  python ironnest_ghost.py elev=15          # raise/lower barrels to 15 deg
  python ironnest_ghost.py fire             # fire controlled gun once
  python ironnest_ghost.py demo             # visible ghost show (sweep + elevate)
"""
import ctypes, ctypes.wintypes as wt, struct, sys, time

DLL = r"C:\Program Files (x86)\Steam\steamapps\common\IRON NEST Heavy Turret Simulator Demo\GameAssembly.dll"  # fallback only; auto-detected from the running game below
PROC_NAME = "Iron Nest Heavy Turret Simulator.exe"
MODNAME   = "GameAssembly.dll"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
def W(fn,res,*a):
    f=getattr(k32,fn); f.restype=res; f.argtypes=a; return f
OpenProcess        = W("OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
CloseHandle        = W("CloseHandle", wt.BOOL, wt.HANDLE)
ReadProcessMemory  = W("ReadProcessMemory", wt.BOOL, wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
WriteProcessMemory = W("WriteProcessMemory", wt.BOOL, wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
VirtualAllocEx     = W("VirtualAllocEx", ctypes.c_void_p, wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD)
CreateRemoteThread = W("CreateRemoteThread", wt.HANDLE, wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p)
WaitForSingleObject= W("WaitForSingleObject", wt.DWORD, wt.HANDLE, wt.DWORD)
VirtualProtectEx    = W("VirtualProtectEx", wt.BOOL, wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD))

def log(*a): print(*a, flush=True)
def fbits(v): return struct.unpack("<I",struct.pack("<f",float(v)))[0]   # float -> 32-bit pattern for mcall
def _le64(v): return struct.pack("<Q", v & 0xffffffffffffffff)

# Main-thread executor dispatch core. Reads command block `cmd`:
#   [+0 flag][+8 func][+0x10 a0][+0x18 a1][+0x20 a2][+0x28 a3][+0x30 ret][+0x38 retf]
# Saves all volatiles, if flag set calls func(a0..a3) (int+xmm), stores ret+xmm0, clears flag.
def _build_dispatch(cmd):
    save=bytes([0x50,0x51,0x52,0x41,0x50,0x41,0x51,0x41,0x52,0x41,0x53,0x9C,
        0x48,0x83,0xEC,0x60,
        0x0F,0x11,0x44,0x24,0x00,0x0F,0x11,0x4C,0x24,0x10,0x0F,0x11,0x54,0x24,0x20,
        0x0F,0x11,0x5C,0x24,0x30,0x0F,0x11,0x64,0x24,0x40,0x0F,0x11,0x6C,0x24,0x50])
    head=bytes([0x48,0xB8])+_le64(cmd)+bytes([0x4C,0x8B,0x10,0x4D,0x85,0xD2])
    disp=bytes([0x48,0x8B,0x48,0x10,0x48,0x8B,0x50,0x18,0x4C,0x8B,0x40,0x20,0x4C,0x8B,0x48,0x28,
        0xF3,0x0F,0x7E,0x40,0x10,0xF3,0x0F,0x7E,0x48,0x18,0xF3,0x0F,0x7E,0x50,0x20,0xF3,0x0F,0x7E,0x58,0x28,
        0x4C,0x8B,0x58,0x08,0x48,0x83,0xEC,0x28,0x41,0xFF,0xD3,0x48,0x83,0xC4,0x28,0x49,0x89,0xC2,
        0x48,0xB8])+_le64(cmd)+bytes([0x4C,0x89,0x50,0x30,0x66,0x48,0x0F,0x7E,0x40,0x38,
        0x48,0xC7,0x00,0x00,0x00,0x00,0x00])
    jz=bytes([0x74,len(disp)])
    restore=bytes([0x0F,0x10,0x44,0x24,0x00,0x0F,0x10,0x4C,0x24,0x10,0x0F,0x10,0x54,0x24,0x20,
        0x0F,0x10,0x5C,0x24,0x30,0x0F,0x10,0x64,0x24,0x40,0x0F,0x10,0x6C,0x24,0x50,
        0x48,0x83,0xC4,0x60,0x9D,0x41,0x5B,0x41,0x5A,0x41,0x59,0x41,0x58,0x5A,0x59,0x58])
    return save+head+jz+disp+restore
_CMD_IMM_OFF = 48   # offset of the cmd imm64 inside the dispatch core (for recovery)

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
    """On-disk path of a loaded module in the target process, so the game can be installed anywhere."""
    snap=CreateToolhelp32Snapshot(TH32_MODULE,pid); m=ME32(); m.dwSize=ctypes.sizeof(ME32)
    ok=Module32First(snap,ctypes.byref(m)); path=None
    while ok:
        if m.mod.decode(errors="ignore").lower()==modname.lower(): path=m.path.decode(errors="ignore"); break
        ok=Module32Next(snap,ctypes.byref(m))
    CloseHandle(snap); return path

def _autodetect_dll(fallback):
    """Resolve GameAssembly.dll from the running game's module list; fall back to the hardcoded path."""
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
    magic,=struct.unpack_from("<H",d,opt); dd=opt+(112 if magic==0x20b else 96)
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

# ---- TurretController field offsets (from ironnest_probe.py) ----
T_GUNS_LIST      = 0x30   # List<GunController>
T_ROT_SPEED      = 0x38   # rotationSpeed (config)
T_MIN_ELEV       = 0x44
T_MAX_ELEV       = 0x48
T_DESIRED_ROT    = 0x128  # <DesiredRotation>
T_CURRENT_ANG    = 0x12c  # <CurrentAngle>
T_DESIRED_ELEV   = 0x130  # <DesiredElevation>  (only used if driveGunElevationsFromController)
T_ROT_VEL        = 0x134  # rotationVelocity
T_DES_ROT_VEL    = 0x13c
T_DES_ROT_VEL_T  = 0x140
T_USING_SPEEDDIAL= 0x144  # bool
# ---- GunController field offsets ----
G_CUR_ELEV       = 0xb4   # <CurrentElevation>
G_DES_ELEV       = 0xb8   # <DesiredElevationAngle>
G_INT_DES_ELEV   = 0xf0   # internalDesiredElevation
G_IS_RELOADING   = 0xd4

class Ghost:
    def __init__(self):
        pid=find_pid()
        if not pid: raise SystemExit("game not running")
        self.pid=pid
        self.h=OpenProcess(PROCESS_ALL,False,pid)
        self.base=module_base(pid)
        rvas=export_rvas(DLL)
        need=["il2cpp_domain_get","il2cpp_domain_get_assemblies","il2cpp_assembly_get_image",
              "il2cpp_image_get_name","il2cpp_class_from_name","il2cpp_class_get_field_from_name",
              "il2cpp_field_static_get_value","il2cpp_runtime_class_init",
              "il2cpp_class_get_method_from_name",
              "il2cpp_class_get_type","il2cpp_type_get_object",
              "il2cpp_thread_attach","il2cpp_thread_detach"]
        self.F={n:self.base+rvas[n] for n in need}
        self._setup_stub()
        log(f"[ok] pid={pid} base=0x{self.base:x}")

    # --- raw memory ---
    def rpm(self,a,s):
        b=(ctypes.c_char*s)(); n=ctypes.c_size_t(0)
        ok=ReadProcessMemory(self.h,ctypes.c_void_p(a),b,s,ctypes.byref(n))
        return bytes(b[:n.value]) if ok else None
    def wpm(self,a,data):
        n=ctypes.c_size_t(0); b=(ctypes.c_char*len(data))(*data)
        return WriteProcessMemory(self.h,ctypes.c_void_p(a),b,len(data),ctypes.byref(n))
    def rptr(self,a): r=self.rpm(a,8); return struct.unpack("<Q",r)[0] if r else 0
    def ru32(self,a): r=self.rpm(a,4); return struct.unpack("<I",r)[0] if r else 0
    def rf32(self,a): r=self.rpm(a,4); return struct.unpack("<f",r)[0] if r else None
    def rb(self,a):   r=self.rpm(a,1); return r[0] if r else None
    def wf32(self,a,v): self.wpm(a,struct.pack("<f",float(v)))
    def wbool(self,a,v): self.wpm(a, b"\x01" if v else b"\x00")
    def rcstr(self,a,m=128):
        if not a: return ""
        r=self.rpm(a,m)
        if not r: return ""
        z=r.find(b'\0'); return r[:z if z>=0 else m].decode(errors="ignore")

    def _setup_stub(self):
        MEM_COMMIT=0x3000
        # simple stub: rcx=[func,a0,a1,a2,a3,ret] -> call func(a0..a3) (C-API only)
        stub=bytes([0x53,0x48,0x89,0xCB,0x48,0x8B,0x03,0x48,0x8B,0x4B,0x08,0x48,0x8B,0x53,0x10,
            0x4C,0x8B,0x43,0x18,0x4C,0x8B,0x4B,0x20,0x48,0x83,0xEC,0x20,0xFF,0xD0,
            0x48,0x83,0xC4,0x20,0x48,0x89,0x43,0x28,0x5B,0xC3])
        self.stub=VirtualAllocEx(self.h,None,len(stub),MEM_COMMIT,0x40)
        self.blk =VirtualAllocEx(self.h,None,0x60,MEM_COMMIT,0x04)
        self.scr =VirtualAllocEx(self.h,None,0x400,MEM_COMMIT,0x04)
        self.wpm(self.stub,stub)
        # managed-safe stub: attach thread, load each arg into BOTH int reg and xmm reg
        # (so float OR pointer/int args both work), call func, store ret, detach.
        # block: [attach, domain, func, a0, a1, a2, a3, detach, ret]
        mstub=bytes([
            0x53,0x56,0x48,0x89,0xCB,0x48,0x83,0xEC,0x28,
            0x48,0x8B,0x4B,0x08,0x48,0x8B,0x03,0xFF,0xD0,0x48,0x89,0xC6,
            0x48,0x8B,0x4B,0x18,0x48,0x8B,0x53,0x20,0x4C,0x8B,0x43,0x28,0x4C,0x8B,0x4B,0x30,
            0xF3,0x0F,0x7E,0x43,0x18,0xF3,0x0F,0x7E,0x4B,0x20,0xF3,0x0F,0x7E,0x53,0x28,0xF3,0x0F,0x7E,0x5B,0x30,
            0x48,0x8B,0x43,0x10,0xFF,0xD0,0x48,0x89,0x43,0x40,
            0x66,0x48,0x0F,0x7E,0x43,0x48,                       # movq [rbx+0x48],xmm0 (float ret)
            0x48,0x89,0xF1,0x48,0x8B,0x43,0x38,0xFF,0xD0,
            0x48,0x83,0xC4,0x28,0x5E,0x5B,0xC3])
        self.mstub=VirtualAllocEx(self.h,None,len(mstub),MEM_COMMIT,0x40)
        self.mblk =VirtualAllocEx(self.h,None,0x80,MEM_COMMIT,0x04)
        self.wpm(self.mstub,mstub)
    def rc(self,func,*args):
        a=list(args)+[0]*(4-len(args))
        self.wpm(self.blk,struct.pack("<6Q",func,a[0],a[1],a[2],a[3],0))
        th=CreateRemoteThread(self.h,None,0,ctypes.c_void_p(self.stub),ctypes.c_void_p(self.blk),0,None)
        if not th: return 0
        WaitForSingleObject(th,5000); CloseHandle(th)
        return self.rptr(self.blk+40)
    def mcall(self,func,*args):
        """Call a managed game method safely (attaches the remote thread to the IL2CPP
        runtime first). Args are raw 64-bit values; use fbits() for float arguments."""
        a=[x & 0xffffffffffffffff for x in list(args)+[0]*(4-len(args))]
        self.wpm(self.mblk,struct.pack("<9Q",self.F["il2cpp_thread_attach"],self.dom,func,
                                       a[0],a[1],a[2],a[3],self.F["il2cpp_thread_detach"],0))
        th=CreateRemoteThread(self.h,None,0,ctypes.c_void_p(self.mstub),ctypes.c_void_p(self.mblk),0,None)
        if not th: return 0
        WaitForSingleObject(th,5000); CloseHandle(th)
        return self.rptr(self.mblk+0x40)
    def mcall_f(self,func,*args):
        """Like mcall, but return the method's float result (from xmm0)."""
        self.mcall(func,*args)
        return self.rf32(self.mblk+0x48)

    # --- MAIN-THREAD executor (hooks TurretController.Update) ---
    # Required for methods that start Unity coroutines / touch UI / animators, which
    # crash if called from the injected (mcall) thread. main_call runs them on the
    # game's main thread by queueing into a command block consumed by an Update hook.
    def ensure_executor(self):
        if getattr(self,"cmd",None): return
        F=self.F
        mi=self.rc(F["il2cpp_class_get_method_from_name"],self.tc,self.cstr(320,"Update"),0)
        upd=self.rptr(mi); self._upd=upd
        head=self.rpm(upd,2)
        if head==b"\xFF\x25":                      # already hooked -> recover cmd/cave
            self.cave=self.rptr(upd+6); self.cmd=self.rptr(self.cave+_CMD_IMM_OFF)
            return
        MEM=0x3000
        self.cmd=VirtualAllocEx(self.h,None,0x80,MEM,0x04)
        orig=self.rpm(upd,15); self._orig15=orig
        cave_code=_build_dispatch(self.cmd)+orig+bytes([0xFF,0x25,0,0,0,0])+_le64(upd+15)
        self.cave=VirtualAllocEx(self.h,None,len(cave_code)+32,MEM,0x40)
        self.wpm(self.cave,cave_code)
        hook=bytes([0xFF,0x25,0,0,0,0])+_le64(self.cave)+bytes([0x90])
        old=wt.DWORD(0)
        VirtualProtectEx(self.h,ctypes.c_void_p(upd),15,0x40,ctypes.byref(old))
        self.wpm(upd,hook)
        VirtualProtectEx(self.h,ctypes.c_void_p(upd),15,old.value,ctypes.byref(old))
    def main_call(self,func,*args,timeout=2.0):
        """Run func(args) on the game's MAIN THREAD. Returns (int_ret, float_ret).
        Requires the game focused (Update must tick). Use for coroutine/UI/animator methods."""
        self.ensure_executor()
        a=[x & 0xffffffffffffffff for x in list(args)+[0]*4][:4]
        self.wpm(self.cmd, struct.pack("<8Q", 0, func, a[0],a[1],a[2],a[3], 0,0))
        self.wpm(self.cmd, struct.pack("<Q", 1))   # arm flag last
        t0=time.time()
        while time.time()-t0<timeout:
            if self.rptr(self.cmd)==0:
                return self.rptr(self.cmd+0x30), self.rf32(self.cmd+0x38)
            time.sleep(0.008)
        return None,None
    def uninstall_executor(self):
        if getattr(self,"_orig15",None) and getattr(self,"_upd",None):
            old=wt.DWORD(0)
            VirtualProtectEx(self.h,ctypes.c_void_p(self._upd),15,0x40,ctypes.byref(old))
            self.wpm(self._upd,self._orig15)
            VirtualProtectEx(self.h,ctypes.c_void_p(self._upd),15,old.value,ctypes.byref(old))

    def cstr(self,off,s):
        a=self.scr+off; self.wpm(a,s.encode()+b"\0"); return a

    # --- focus (game pauses Update() when unfocused) ---
    def focus_game(self):
        hwnds=[]
        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(hw,l):
            p=wt.DWORD(); u32.GetWindowThreadProcessId(hw, ctypes.byref(p))
            if p.value==self.pid and u32.IsWindowVisible(hw): hwnds.append(hw)
            return True
        u32.EnumWindows(cb,0)
        if not hwnds: return False
        hw=hwnds[0]; self.hwnd=hw
        fg=u32.GetForegroundWindow(); ftid=u32.GetWindowThreadProcessId(fg,0); ctid=k32.GetCurrentThreadId()
        u32.AttachThreadInput(ctid,ftid,True)
        u32.ShowWindow(hw,9); u32.BringWindowToTop(hw); u32.SetForegroundWindow(hw); u32.SetActiveWindow(hw)
        u32.AttachThreadInput(ctid,ftid,False)
        time.sleep(0.4)
        return u32.GetForegroundWindow()==hw

    # --- IL2CPP image / class / object helpers ---
    def _build_images(self):
        F=self.F; self.dom=self.rc(F["il2cpp_domain_get"])
        if not self.dom: raise SystemExit("il2cpp not ready - load into a mission")
        sp=self.scr+0; self.wpm(sp,b"\0"*8)
        arr=self.rc(F["il2cpp_domain_get_assemblies"],self.dom,sp); cnt=self.rptr(sp)
        self.images={}
        for j in range(min(cnt,400)):
            asm=self.rptr(arr+j*8)
            if not asm: continue
            img=self.rc(F["il2cpp_assembly_get_image"],asm)
            self.images[self.rcstr(self.rc(F["il2cpp_image_get_name"],img))]=img
        self.csharp=self.images.get("Assembly-CSharp.dll",0)
        self.core=self.images.get("UnityEngine.CoreModule.dll",0)
        if not self.csharp: raise SystemExit("Assembly-CSharp not found")

    def get_class(self,name,ns="",image=None,slot=320):
        return self.rc(self.F["il2cpp_class_from_name"], image or self.csharp,
                       self.cstr(slot,ns), self.cstr(slot+80,name))

    def find_objects(self,clsname,ns="",image=None):
        """Return live instance pointers of a MonoBehaviour type via FindObjectsOfType."""
        kl=self.get_class(clsname,ns,image)
        if not kl: return []
        self.rc(self.F["il2cpp_runtime_class_init"],kl)
        ty=self.rc(self.F["il2cpp_class_get_type"],kl)
        tyobj=self.rc(self.F["il2cpp_type_get_object"],ty)
        res=self.mcall(self._m_findobjs, tyobj, self._mi_findobjs)
        if not res: return []
        n=self.rptr(res+0x18)
        return [self.rptr(res+0x20+k*8) for k in range(min(n,64)) if self.rptr(res+0x20+k*8)]
    def find_one(self,clsname,ns="",image=None):
        o=self.find_objects(clsname,ns,image); return o[0] if o else 0

    # --- resolve singleton + guns + fire-control instances ---
    def resolve(self):
        F=self.F
        self._build_images()
        self.tc=self.get_class("TurretController")
        self.rc(F["il2cpp_runtime_class_init"],self.tc)
        fld=self.rc(F["il2cpp_class_get_field_from_name"],self.tc,self.cstr(64,"Instance"))
        ob=self.scr+128; self.wpm(ob,b"\0"*8)
        self.rc(F["il2cpp_field_static_get_value"],fld,ob)
        self.inst=self.rptr(ob)
        if not self.inst: raise SystemExit("TurretController.Instance is null - load into a mission")
        self.guns=self._read_guns()
        # FindObjectsOfType plumbing
        obj_cls=self.get_class("Object","UnityEngine",self.core)
        self._mi_findobjs=self.rc(F["il2cpp_class_get_method_from_name"],obj_cls,self.cstr(320,"FindObjectsOfType"),1)
        self._m_findobjs=self.rptr(self._mi_findobjs)
        # universal dial operator: DialInteractable.SetDialValue(float)
        dcls=self.get_class("DialInteractable")
        self._mi_setdial=self.rc(F["il2cpp_class_get_method_from_name"],dcls,self.cstr(320,"SetDialValue"),1)
        self._m_setdial=self.rptr(self._mi_setdial)
        # fire-control instances
        self.computer=self.find_one("ArtilleryComputer")
        self.printer =self.find_one("FireMissionCardPrinter")
        log(f"[ok] Turret=0x{self.inst:x} guns={[hex(x) for x in self.guns]}")
        log(f"[ok] ArtilleryComputer=0x{self.computer:x} FireMissionCardPrinter=0x{self.printer:x}")
        return self.inst

    def _read_guns(self):
        lst=self.rptr(self.inst+T_GUNS_LIST)
        if not lst: return []
        items=self.rptr(lst+0x10); n=self.ru32(lst+0x18)
        return [self.rptr(items+0x20+k*8) for k in range(min(n,16)) if self.rptr(items+0x20+k*8)]

    def method(self,name,argc):
        m=self.rc(self.F["il2cpp_class_get_method_from_name"],self.tc,self.cstr(200,name),argc)
        return (self.rptr(m), m) if m else (0,0)

    # --- dial operator (the ghost's knob-turning hand) ---
    def set_dial(self,dialptr,value):
        if dialptr: self.mcall(self._m_setdial, dialptr, fbits(value), self._mi_setdial)
    def dial_value(self,dialptr): return self.rf32(dialptr+0x9c) if dialptr else None
    # named dial accessors
    def d_range(self):   return self.rptr(self.computer+0x28) if self.computer else 0
    def d_powder(self):  return self.rptr(self.computer+0x38) if self.computer else 0
    def d_bearing(self): return self.rptr(self.printer+0x40) if self.printer else 0
    def d_shell(self):   return self.rptr(self.printer+0x48) if self.printer else 0

    # --- state ---
    def bearing(self):   return self.rf32(self.inst+T_CURRENT_ANG)
    def des_bearing(self):return self.rf32(self.inst+T_DESIRED_ROT)
    def elevation(self):
        es=[self.rf32(g+G_CUR_ELEV) for g in self.guns]
        return sum(es)/len(es) if es else None
    def state(self):
        return dict(bearing=self.bearing(), desired_bearing=self.des_bearing(),
                    elevation=self.elevation(),
                    min_elev=self.rf32(self.inst+T_MIN_ELEV), max_elev=self.rf32(self.inst+T_MAX_ELEV),
                    reloading=[self.rb(g+G_IS_RELOADING) for g in self.guns])

    # --- commands (the ghost's hands) ---
    def aim_bearing(self, deg):
        self.wbool(self.inst+T_USING_SPEEDDIAL, False)   # position-servo mode
        self.wf32(self.inst+T_DESIRED_ROT, deg)
    def set_elevation(self, deg):
        lo=self.rf32(self.inst+T_MIN_ELEV) or 0.0; hi=self.rf32(self.inst+T_MAX_ELEV) or 60.0
        deg=max(lo,min(hi,deg))
        # write both the turret-level target and each gun's target so neither path
        # (driveGunElevationsFromController vs per-gun) can override the other.
        self.wf32(self.inst+T_DESIRED_ELEV, deg)
        for g in self.guns:
            self.wf32(g+G_DES_ELEV, deg); self.wf32(g+G_INT_DES_ELEV, deg)
    def fire(self):
        mp,mi=self.method("FireControlledGun",0)
        if mp: self.rc(mp, self.inst, mi)

    # --- closed-loop: command then wait for the servo to arrive ---
    def slew_to(self, deg, tol=0.6, timeout=20):
        self.aim_bearing(deg); t0=time.time()
        while time.time()-t0<timeout:
            if abs((self.bearing() or 0)-deg)<tol: return True
            time.sleep(0.05)
        return False
    def elevate_to(self, deg, tol=0.6, timeout=20):
        self.set_elevation(deg); t0=time.time()
        while time.time()-t0<timeout:
            if abs((self.elevation() or 0)-deg)<tol: return True
            time.sleep(0.05)
        return False

def main():
    args=sys.argv[1:]
    g=Ghost()
    foc=g.focus_game();
    g.resolve()
    st=g.state()
    log(f"focus={'ok' if foc else 'FAILED (turret will not move unless game is focused)'}")
    log("live state:")
    for k,v in st.items(): log(f"   {k:16} = {v}")

    rot=elev=slew=None; do_fire=False; do_demo=False
    for a in args:
        if a.startswith("rot="): rot=float(a[4:])
        elif a.startswith("elev="): elev=float(a[5:])
        elif a.startswith("slew="): slew=float(a[5:])
        elif a=="fire": do_fire=True
        elif a=="demo": do_demo=True

    if slew is not None:
        tgt=(st["bearing"] or 0)+slew
        log(f"[ghost] slew to {tgt:.1f} deg ..."); ok=g.slew_to(tgt); log(f"  arrived={ok} bearing={g.bearing():.2f}")
    if rot is not None:
        log(f"[ghost] aim bearing {rot:.1f} ..."); ok=g.slew_to(rot); log(f"  arrived={ok} bearing={g.bearing():.2f}")
    if elev is not None:
        log(f"[ghost] elevate to {elev:.1f} ..."); ok=g.elevate_to(elev); log(f"  arrived={ok} elevation={g.elevation():.2f}")
    if do_demo:
        base=st["bearing"] or 0
        log("[ghost] DEMO: watch the handwheels turn themselves...")
        g.elevate_to(18); log(f"  barrels up -> {g.elevation():.1f}")
        g.slew_to(base+25); log(f"  traverse right -> {g.bearing():.1f}")
        g.slew_to(base-25); log(f"  traverse left  -> {g.bearing():.1f}")
        g.slew_to(base);    log(f"  return center  -> {g.bearing():.1f}")
        g.elevate_to(2);    log(f"  barrels down   -> {g.elevation():.1f}")
        log("[ghost] demo complete.")
    if do_fire:
        log("[ghost] FIRE"); g.fire()

    if rot is None and elev is None and slew is None and not do_demo and not do_fire:
        log("\n(read-only. Pass rot=20 / slew=+25 / elev=15 / fire / demo to drive it.)")

if __name__=="__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc()
