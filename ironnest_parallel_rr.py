"""
IRON NEST - PARALLEL (pipelined) round-robin artillery killer.

GOAL (user): even when it's NOT a gun's turn to fire, it should already have done
every readying step -- line drawing, card generation, chambering, charging, AND
elevation -- so that when the other gun's shot is done, all that remains for THIS
gun is to rotate the (shared) turret to its bearing and fire.

HARD CONSTRAINT: the main-thread call executor is single. Two OS processes cannot
both drive the game (their inline hooks share one command queue). So "parallel"
means ONE process that interleaves both guns' prep steps; the game-side mechanics
(cylinder ramming, powder loading, elevation servos) then genuinely run at the same
time, while only the SHARED turret bearing is serialized.

PIPELINE per volley:
  1. TARGET + CARD  (serial -- the calculator/printer dials are shared hardware)
  2. STOCK + LOAD   (PARALLEL -- each gun's cylinder/powder is independent; loads
                     are driven by NON-BLOCKING clicks so both animate together)
  3. ELEVATE        (PARALLEL -- per-gun independent elevation servos)
  4. FIRE           (SERIAL  -- rotate shared bearing to each gun in turn, fire)
Between volleys both guns re-stage in parallel, overlapping both reload recoveries.

  usage:  python ironnest_parallel_rr.py [N=4]
"""
import sys, os, time, struct, re, subprocess, random

GHOST = os.path.dirname(os.path.abspath(__file__))
SCR   = r"C:\Users\Owner\AppData\Local\Temp\claude\C--Users-Owner\776c532f-07d9-4785-9015-6eaac32a484e\scratchpad"
sys.path.insert(0, GHOST)
import ironnest_ghost as G
PY = sys.executable

# ---------------- module helpers ----------------
def rstr(g, p):
    if not p: return ""
    n = g.ru32(p+0x10); return g.rpm(p+0x14, n*2).decode("utf-16-le","ignore") if 0<n<400 else ""
def meth(g, cls, name, argc):
    F=g.F; mi=g.rc(F["il2cpp_class_get_method_from_name"], cls, g.cstr(320,name), argc); return g.rptr(mi), mi
def gn(g, gp): return rstr(g, g.rptr(gp+0x20))

# ---------------- per-gun core (parameterized prep / fire) ----------------
class Gun:
    def __init__(self, g, M, name):
        self.g=g; self.M=M; self.name=name
        rcs=[r for r in g.find_objects("ArtilleryReloadController") if gn(g, g.rptr(r+0x68))==name]
        if not rcs:
            have=sorted({gn(g, g.rptr(r+0x68)) for r in g.find_objects("ArtilleryReloadController")})
            raise SystemExit("gun %r not found (have %s)" % (name, have))
        self.rc  = rcs[0]
        self.cyl = [c for c in g.find_objects("CylinderShellSelector") if g.rptr(c+0x40)==self.rc][0]
        self.pc  = [p for p in g.find_objects("PowderChargeController")  if g.rptr(p+0x48)==self.rc][0]
        self.gun = g.rptr(self.rc+0x68)
        self.gun_idx = g.guns.index(self.gun) if self.gun in g.guns else 0
        lst=g.rptr(self.rc+0x28); self.it2=g.rptr(lst+0x10)
        self.names={i: rstr(g, g.rptr(g.rptr(self.it2+0x20+i*8)+0x10)) for i in range(g.ru32(lst+0x18))}
        self.MODEL_FILE=os.path.join(GHOST, "_cylinder_model_%s.txt" % name)
        pr=g.printer
        sl=g.rptr(pr+0xb8); items=g.rptr(sl+0x10); n=g.ru32(sl+0x18) if sl else 0
        self.SHELLDEF={rstr(g, g.rptr(g.rptr(items+0x20+i*8)+0x18)): g.rptr(items+0x20+i*8) for i in range(min(n,16))}
        self._slotbuf=G.VirtualAllocEx(g.h, None, 8, 0x3000, 0x04)
        # per-mission state
        self.ok=True; self.ready=False; self.stocked=False; self.elevated=False; self.phase="IDLE"
        self.last_click=0.0; self.target=None; self.model=None
        self.C_BEAR=0.0; self.C_ELEV=0.0; self.C_CHG=3; self.raw=0.0; self.SHELL="HE"; self.err=False

    # ---- low-level button / state helpers (all bound to THIS gun) ----
    def goname(self, o):
        M=self.M; g=self.g; r=g.main_call(M['gname'][0], o, M['gname'][1])[0]; return rstr(g, r) if r else ""
    def shtype(self, nm):
        if not nm: return "--"
        if "HCHE" in nm: return "HCHE"
        if "HE" in nm: return "HE"
        if "AP" in nm: return "AP"
        return "--"
    def canfire(self):
        M=self.M; g=self.g
        return ((g.main_call(M['can'][0], self.gun, M['can'][1])[0] or 0) & 0xff)==1
    def chambered(self):  return self.g.rptr(self.rc+0x38)!=0
    def state(self):      return self.names.get(self.g.ru32(self.rc+0x48), "?")
    def active(self, b):  return bool(b) and self.g.rb(b+0xa0)==1
    def chambered_charge(self):
        M=self.M; g=self.g; bp=g.main_call(M['bp'][0], self.gun, M['bp'][1])[0]
        return g.ru32(bp+0x28) if bp else -1
    def chambered_type(self):
        M=self.M; g=self.g; bp=g.main_call(M['bp'][0], self.gun, M['bp'][1])[0]
        return self.shtype(self.goname(bp)) if bp else "--"
    def press(self, b):                  # BLOCKING click (serial ops: calc button, stocking)
        M=self.M; g=self.g
        g.main_call(M['down'][0], b, M['down'][1]); time.sleep(0.04); g.main_call(M['up'][0], b, M['up'][1])
        t0=time.time()
        while self.active(b) and time.time()-t0<3: time.sleep(0.03)
    def click_nb(self, b):               # NON-BLOCKING click (parallel load ticks -> animations overlap)
        M=self.M; g=self.g
        g.main_call(M['down'][0], b, M['down'][1]); time.sleep(0.04); g.main_call(M['up'][0], b, M['up'][1])
    def b_cylLoad(self): return self.g.rptr(self.cyl+0x50)
    def b_pwdLoad(self): return self.g.rptr(self.pc+0x40)
    def b_adv(self):
        g=self.g; sd=g.rptr(self.it2+0x20 + g.ru32(self.rc+0x48)*8); return g.rptr(sd+0x30) if sd else 0
    def b_charges(self):
        g=self.g; cl=g.rptr(self.pc+0x20); it=g.rptr(cl+0x10); n=g.ru32(cl+0x18) if cl else 0
        return [g.rptr(it+0x20+i*8) for i in range(min(n,8))] if it else []
    def set_gun_elev(self, deg):         # INDEPENDENT per-gun elevation (NOT turret-level / other gun)
        g=self.g; lo=g.rf32(g.inst+0x44) or 0.0; hi=g.rf32(g.inst+0x48) or 60.0; deg=max(lo,min(hi,deg))
        g.wf32(self.gun+0xb8, deg); g.wf32(self.gun+0xf0, deg)
    def elev_done(self): return abs((self.g.rf32(self.gun+0xb4) or 0)-self.C_ELEV)<0.25
    def snap_elev(self):
        g=self.g; g.wf32(self.gun+0xb4, self.C_ELEV); g.wf32(self.gun+0xb8, self.C_ELEV)

    # ---- revolver loader (stock-once / fire-many, persisted, gun-specific) ----
    def occ_list(self):
        g=self.g; bl=g.rptr(self.cyl+0x30); bit=g.rptr(bl+0x10); nb=g.ru32(bl+0x18) if bl else 0
        return [bool(g.rptr(bit+0x20+i*8)) for i in range(nb)] if 0<nb<=12 else []
    def rev_steady(self):
        g=self.g; sb=g.rb(self.cyl+0x88); return g.ru32(self.rc+0x48)==3 and sb is not None
    def rev_pull(self):
        g=self.g; M=self.M
        if not self.rev_steady(): return False
        mb=g.rptr(self.cyl+0x60)
        if not mb or g.rb(mb+0xa0)!=1: return False
        g.main_call(M['down'][0],mb,M['down'][1]); time.sleep(0.12); g.main_call(M['up'][0],mb,M['up'][1]); time.sleep(1.5)
        return g.rpm(self.rc+0x48,4) is not None
    def move_active(self):                    # is the cylinder rotate-button live right now? (may be true mid-leveling, before BreechOpen)
        g=self.g; mb=g.rptr(self.cyl+0x60); return bool(mb) and g.rb(mb+0xa0)==1
    def rev_pull_live(self):                  # rotate ONE step whenever the moveButton is active -- works pre-BreechOpen (during leveling).
        g=self.g; M=self.M                    # Safe: only clicks an active UI button; no cylinder method calls / goname.
        mb=g.rptr(self.cyl+0x60)
        if not mb or g.rb(mb+0xa0)!=1: return False
        g.main_call(M['down'][0],mb,M['down'][1]); time.sleep(0.12); g.main_call(M['up'][0],mb,M['up'][1]); time.sleep(0.9)
        return True
    def breech_type_steady(self):             # ACTUAL breech shell type, ONLY when steady (goname is crash-safe only then)
        g=self.g
        if not self.rev_steady(): return None
        bl=g.rptr(self.cyl+0x30); bit=g.rptr(bl+0x10); bp0=g.rptr(bit+0x20) if bit else 0
        return self.shtype(self.goname(bp0)) if bp0 else None
    def rev_loadmodel(self):
        try:
            parts=open(self.MODEL_FILE).read().strip().split(",")
            if len(parts)>=6: return [(p if p in ("HE","AP","HCHE") else None) for p in parts[:6]]
        except Exception: pass
        return None
    def rev_insert(self, typ):            # insert a shell straight into THIS cylinder; returns filled slot or -1
        g=self.g; M=self.M
        if not self.rev_steady() or typ not in self.SHELLDEF: return -1
        before=self.occ_list()
        g.wpm(self._slotbuf, b"\0"*8)
        g.main_call(M['insert'][0], self.cyl, self.SHELLDEF[typ], self._slotbuf, M['insert'][1]); time.sleep(0.5)
        if g.rpm(self.rc+0x48,4) is None: return -1
        after=self.occ_list()
        for i in range(min(len(before),len(after),6)):
            if (not before[i]) and after[i]: return i
        return -1
    def revolver_load(self, want):
        g=self.g; t0=time.time()
        while not self.rev_steady() and time.time()-t0<90:                    # auto-cycles to BreechOpen after a shot
            if hasattr(g,"reseal_valves"): g.reseal_valves()                  # a leaking Cylinder valve blocks the breech-open -> reseal during the wait
            time.sleep(0.5)
        if not self.rev_steady():
            print("  [%s] revolver: not back to BreechOpen after 90s -> skip" % self.name); return False
        model=[None]*6; o=self.occ_list(); pm=self.rev_loadmodel(); stocked=False
        if pm is not None and len(o)==6:
            pmo=[x is not None for x in pm]
            if pmo==o: model[:]=pm; stocked=True
            elif pm[0] is not None and ([False]+pmo[1:])==o: model[:]=[None]+pm[1:]; stocked=True
            if stocked and not any(model): stocked=False
        if not stocked and not any(o):
            print("  [%s] revolver: empty cylinder -> stocking 3xHE + 3xAP" % self.name)
            for typ in ["HE","HE","HE","AP","AP","AP"]:
                slot=self.rev_insert(typ)
                if slot<0: print("  [%s] revolver: insert %s failed" % (self.name,typ)); break
                model[slot]=typ
            stocked=True
        elif not stocked:
            _bl=g.rptr(self.cyl+0x30); _bit=g.rptr(_bl+0x10); _nb=g.ru32(_bl+0x18) if _bl else 0
            for i in range(min(_nb,6)):
                bp=g.rptr(_bit+0x20+i*8)
                if bp:
                    nm=self.goname(bp); model[i]=("HCHE" if "HCHE" in nm else "AP" if "AP" in nm else "HE" if "HE" in nm else "?")
            print("  [%s] revolver: %d leftover -> model=%s" % (self.name,sum(o),[m or "-" for m in model]))
            stocked=True
        present=[m for m in model if m]
        if len(present) < 4 and None in model:                              # cylinder running low -> refill toward a balanced 3 HE + 3 AP
            need_he=max(0,3-present.count("HE")); need_ap=max(0,3-present.count("AP"))   # (FULL cylinders rotate reliably; SPARSE ones desync)
            fill=["HE"]*need_he+["AP"]*need_ap
            if want not in present and want not in fill: fill=[want]+fill
            for typ in fill:
                if None not in model: break
                slot=self.rev_insert(typ)
                if slot<0: break
                model[slot]=typ
            print("  [%s] revolver: topped up low cylinder -> %s" % (self.name,[m or '-' for m in model]))
        elif want not in present and None in model:                         # full enough, only the wanted type missing -> single insert
            print("  [%s] revolver: %s not in stock -> inserting a fresh %s" % (self.name,want,want))
            slot=self.rev_insert(want)
            if slot>=0: model[slot]=want
        if want in [m for m in model if m]:           # rotate wanted shell to breech AND settle so load button engages
            def breech_type():                        # ACTUAL breech shell (goname ONLY when steady -> crash-safe); self-corrects model desync
                if not self.rev_steady(): return None
                bl=g.rptr(self.cyl+0x30); bit=g.rptr(bl+0x10); bp0=g.rptr(bit+0x20) if bit else 0
                return self.shtype(self.goname(bp0)) if bp0 else None
            stalls=0
            for _ in range(12):
                if hasattr(g,"reseal_valves"): g.reseal_valves()             # reseal any Cylinder valve leak so this rotation isn't pressure-blocked
                lb=g.rptr(self.cyl+0x50); bt=breech_type()
                if bt==want and lb and g.rb(lb+0xa0)==1:
                    model[0]=want; break              # confirmed: the wanted shell is genuinely at the breech
                if self.rev_pull():
                    model[:]=model[1:]+model[:1]; stalls=0
                else:
                    stalls+=1
                    if stalls>=4: break               # cylinder refuses to rotate -> give up (don't hang)
                    t1=time.time()
                    while not self.rev_steady() and time.time()-t1<5: time.sleep(0.2)
            bt=breech_type()
            if bt and bt!=want: print("  [%s] revolver: WARN breech=%s but wanted %s (model desync)" % (self.name, bt, want))
        try: open(self.MODEL_FILE,"w").write(",".join(m if m else "-" for m in model))
        except Exception: pass
        self.model=model[:]                            # keep the live model so the next mission can pre-cycle off-steady
        print("  [%s] revolver: stock=%s -> breech=%s" % (self.name,[m or "-" for m in model],model[0] or "empty"))
        return True

    # ---- PHASE 1: CARD (uses the SHARED computer/printer -> call serially) ----
    def compute_card(self, bearing, rng, powder, shell):
        g=self.g; ac=g.computer; pr=g.printer
        self.SHELL = shell if shell in ("HE","AP") else "HE"
        rangeDial=g.rptr(ac+0x28); powderDial=g.rptr(ac+0x38); calcBtn=g.rptr(ac+0x48)
        bearingDial=g.rptr(pr+0x40); shellDial=g.rptr(pr+0x48)
        sl=g.rptr(pr+0xb8); items=g.rptr(sl+0x10); n=g.ru32(sl+0x18) if sl else 0
        he_idx=next((i for i in range(min(n,16)) if rstr(g,g.rptr(g.rptr(items+0x20+i*8)+0x18))=="HE"),3)
        ap_idx=next((i for i in range(min(n,16)) if rstr(g,g.rptr(g.rptr(items+0x20+i*8)+0x18))=="AP"),1)
        shell_idx=ap_idx if self.SHELL=="AP" else he_idx
        def calc(p):
            g.set_dial(rangeDial,rng); g.set_dial(powderDial,p)
            g.set_dial(bearingDial,bearing); g.set_dial(shellDial,shell_idx); time.sleep(0.4)
            self.press(calcBtn); time.sleep(2.2)
            return g.rf32(ac+0xb4), g.rb(ac+0xa9)
        powder=6                                  # ALWAYS max charge -> flattest trajectory -> LOWEST elevation -> least servo travel (faster firing rate)
        elev,err=calc(6)
        if err or elev<=0:                        # charge 6 overshoots a very close target -> step DOWN to the highest charge that still reaches
            for trial in [5,4,3,2,1]:
                elev,err=calc(trial)
                if not err and elev>0: powder=trial; break
        def tmptext(p): return rstr(g, g.rptr(p+0xe0)) if p else ""
        cards=g.find_objects("FireMissionCard"); card={}
        if cards:
            c=cards[0]
            card=dict(bearing=tmptext(g.rptr(c+0x28)), elevation=tmptext(g.rptr(c+0x30)),
                      powder=tmptext(g.rptr(c+0x38)), shell=tmptext(g.rptr(c+0x40)))
        def num(s):
            m=re.search(r"-?\d+\.?\d*", s or ""); return float(m.group()) if m else None
        self.C_BEAR=num(card.get("bearing")) if card.get("bearing") else bearing
        self.C_ELEV=num(card.get("elevation")) if card.get("elevation") else elev
        self.C_CHG=int(num(card.get("powder")) or powder)
        self.err=bool(err); self.raw=((-self.C_BEAR+180)%360)-180
        if (self.C_ELEV or 0)<=0 or err:        # calculator couldn't solve -> turret can still fire out-of-map: max charge + max elevation
            self.C_ELEV=g.rf32(g.inst+0x48) or 60.0; self.C_CHG=6
            print("  [%s] CARD rot=%.1f beyond calculator -> firing MAX (elev=%.2f chg=6 shell=%s)" %
                  (self.name,self.C_BEAR,self.C_ELEV,self.SHELL))
        else:
            print("  [%s] CARD rot=%.1f elev=%.2f chg=%d shell=%s" %
                  (self.name,self.C_BEAR,self.C_ELEV,self.C_CHG,self.SHELL))
        return True                             # never skip for range -- the turret reaches out-of-map positions

    # ---- PHASE 2 tick: ONE non-blocking step of the load state machine ----
    def prep_tick(self):
        if self.ready: return True
        g=self.g
        if self.canfire(): self.ready=True; return True
        now=time.time()
        if now-self.last_click < 0.6: return False        # cooldown: let last click register + animate
        if not self.chambered() and self.active(self.b_cylLoad()):
            self.click_nb(self.b_cylLoad()); self.last_click=now; return False
        if self.state()=="SelectPowderCharge" and g.ru32(self.pc+0x80) < self.C_CHG:
            cb=[b for b in self.b_charges() if self.active(b)]
            if cb: self.click_nb(cb[0]); self.last_click=now; return False
        if self.active(self.b_pwdLoad()) and g.ru32(self.pc+0x80) >= self.C_CHG:
            self.click_nb(self.b_pwdLoad()); self.last_click=now; return False
        if g.rb(self.cyl+0x88)==1 and not self.chambered():
            return False                                   # shell at breech not chambered yet -> wait
        if self.active(self.b_adv()):
            self.click_nb(self.b_adv()); self.last_click=now; return False
        return False

    # ---- PHASE 4: FIRE -- rotate the SHARED bearing to this gun, snap, fire ----
    def aim_and_fire(self, rng):
        g=self.g; M=self.M
        g.slew_to(self.raw, tol=0.4, timeout=20)
        g.wf32(g.inst+0x128, self.raw); g.wf32(g.inst+0x12c, self.raw)        # snap EXACT bearing
        self.set_gun_elev(self.C_ELEV)
        t0=time.time()
        while time.time()-t0<8:
            if self.elev_done(): break
            time.sleep(0.2)
        self.snap_elev(); time.sleep(0.2)                                     # snap EXACT elevation (already staged)
        g.wpm(g.inst+0x138, struct.pack("<i", self.gun_idx))                  # controlled gun = THIS gun
        if not self.canfire(): print("  [%s] WARN: not CanFire at fire time" % self.name)
        g.main_call(M['fcg'][0], g.inst, M['fcg'][1])
        print("  [%s] SHELL AWAY  rot=%.2f elev=%.2f  (range %.2f km, %d chg, %s)" %
              (self.name, g.bearing(), g.rf32(self.gun+0xb4), rng, self.C_CHG, self.SHELL))
        self.ready=False

# ---------------- parallel staging (the heart of the pipeline) ----------------
def stage(guns):
    """Bring every gun in `guns` to READY (loaded + charged + elevated) IN PARALLEL.
       Cards are assumed already computed (compute_card, serial). Only the bearing is left."""
    live=[gn for gn in guns if gn.ok]
    if not live: return
    # stock + queue elevation (serial per gun; quick) -- elevation servo then travels during the load tick
    for gn in live:
        gn.last_click=0.0
        if gn.canfire() and (gn.chambered_charge()!=gn.C_CHG or gn.chambered_type()!=gn.SHELL):  # wrong charge/shell -> discharge & reload
            print("  [%s] wrong load (have %s/%d, want %s/%d) -> discharging to reload" %
                  (gn.name, gn.chambered_type(), gn.chambered_charge(), gn.SHELL, gn.C_CHG))
            gn.g.wpm(gn.g.inst+0x138, struct.pack("<i", gn.gun_idx))   # MUST select THIS gun, else FireControlledGun fires whoever is controlled
            gn.g.main_call(gn.M['fcg'][0], gn.g.inst, gn.M['fcg'][1])
            t1=time.time()
            while gn.canfire() and time.time()-t1<6: time.sleep(0.1)
            time.sleep(2.0)
        if gn.canfire():                       # already loaded with the right charge -> nothing to load, just (re)elevate
            gn.ready=True; gn.set_gun_elev(gn.C_ELEV)
        elif gn.revolver_load(gn.SHELL):
            gn.set_gun_elev(gn.C_ELEV)         # << start the elevation servo NOW, concurrent with loading
        else:
            gn.ok=False
    live=[gn for gn in live if gn.ok]
    # PARALLEL load: tick both state machines; non-blocking clicks let cylinder/powder animate together
    print("  >> loading %s in parallel ..." % "+".join(gn.name for gn in live))
    t0=time.time()
    while not all(gn.ready for gn in live) and time.time()-t0 < 130:
        for gn in live:
            if not gn.ready: gn.prep_tick()
        time.sleep(0.18)
    # PARALLEL elevation finish: both servos have been travelling; wait then snap exact
    t0=time.time()
    while not all(gn.elev_done() for gn in live if gn.ready) and time.time()-t0 < 40:
        time.sleep(0.2)
    for gn in live:
        if gn.ready: gn.snap_elev()
    for gn in live:
        bp=gn.g.main_call(gn.M['bp'][0], gn.gun, gn.M['bp'][1])[0]
        print("  [%s] STAGED: shell=%s chg=%d elev=%.2f CanFire=%s  (awaiting bearing)" %
              (gn.name, gn.shtype(gn.goname(bp)) if bp else "none", gn.chambered_charge(),
               gn.g.rf32(gn.gun+0xb4), gn.ready))

# ---------------- powder-charge replenishment (buy back what each shot spends) ----------------
def replenish_charges(g, M):
    """Buy 'PowderCharges' (each purchase = +20, capped at maxCapacity) so the SHARED powder
       inventory never empties -- an empty inventory disables the charge buttons and stalls the load.
       Tops up whenever there's room for a full +20, so it actually buys ~once every several shots."""
    pc=M.get('pc')
    if not pc or not pc.get('inv') or not pc.get('drag') or not pc.get('slot'): return 0
    inv=pc['inv']; mx=pc['max']; bought=0
    while g.ru32(inv+0x58) <= mx-20 and bought<8:
        before=g.ru32(inv+0x58)
        g.main_call(M['move1'][0], pc['drag'], pc['itemslot'], M['move1'][1]); time.sleep(0.5)
        g.main_call(M['att'][0], pc['slot'], M['att'][1]); time.sleep(1.5)
        if g.ru32(inv+0x58) <= before: break        # buy didn't register -> stop (avoid spinning)
        bought+=1
    if bought: print("  >> bought %dx PowderCharges -> powder inventory=%d/%d" % (bought, g.ru32(inv+0x58), mx), flush=True)
    return bought

# ---------------- volley: FULLY ASYNC -- no gun waits on another's cylinder cycling ----------------
def fire_volley(g, order):
    """Every gun's prep runs CONCURRENTLY: cylinder-cycle wait -> stock -> chamber/charge/ram -> elevate.
       A gun whose cylinder is still cycling is SKIPPED (not blocked on), so the other gun keeps prepping.
       The shared turret bearing is the only serial resource: whichever gun is READY first fires first
       (turret slews to the ready gun nearest the current bearing). Returns the guns that fired."""
    live=[gn for gn in order if gn.ok]
    if not live: return []
    for gn in live: gn.stocked=False; gn.ready=False; gn.last_click=0.0
    # pre-pass: clear any WRONG leftover load (discharge) before slewing
    for gn in live:
        if gn.canfire() and (gn.chambered_charge()!=gn.C_CHG or gn.chambered_type()!=gn.SHELL):
            print("  [%s] wrong load (have %s/%d, want %s/%d) -> discharging to reload" %
                  (gn.name, gn.chambered_type(), gn.chambered_charge(), gn.SHELL, gn.C_CHG))
            g.wpm(g.inst+0x138, struct.pack("<i", gn.gun_idx))   # select THIS gun before firing
            g.main_call(gn.M['fcg'][0], g.inst, gn.M['fcg'][1])
            t1=time.time()
            while gn.canfire() and time.time()-t1<6: time.sleep(0.1)
            time.sleep(2.0)
    # queue all elevations immediately + optimistically pre-slew to the first gun (overlaps load)
    for gn in live: gn.set_gun_elev(gn.C_ELEV)
    g.aim_bearing(live[0].raw)
    def advance(gn):                            # ONE prep step; NEVER blocks on a cylinder that is still cycling
        if gn.ready or not gn.ok: return
        if not gn.stocked:
            if gn.canfire():
                gn.ready=True; gn.stocked=True
            elif gn.rev_steady():               # THIS gun's cylinder is back to BreechOpen -> stock it now
                gn.stocked=True
                if not gn.revolver_load(gn.SHELL): gn.ok=False
            # else: still cycling -> skip; the OTHER gun keeps prepping in the meantime
        else:
            gn.prep_tick()
    print("  >> prepping %s FULLY ASYNC (no gun waits on another's cylinder cycling) ..." % "+".join(gn.name for gn in live), flush=True)
    fired=[]; remaining=list(live); t0=time.time()
    while remaining and time.time()-t0<240:
        for gn in remaining: advance(gn)
        remaining=[gn for gn in remaining if gn.ok]
        cand=[gn for gn in remaining if gn.ready and gn.elev_done()]
        if not cand:
            time.sleep(0.15); continue
        gn=min(cand, key=lambda x: abs(((g.bearing() or 0)-x.raw+180)%360-180))   # ready gun nearest current bearing -> least slew
        print("  [%s] ready first -> slewing to %.1f and firing" % (gn.name, gn.C_BEAR), flush=True)
        g.aim_bearing(gn.raw)
        tb=time.time()
        while time.time()-tb<25:
            for o in remaining:
                if o is not gn: advance(o)       # keep prepping the OTHER gun during this gun's slew
            if abs((g.bearing() or 0)-gn.raw)<0.4 and gn.elev_done(): break
            time.sleep(0.15)
        g.wf32(g.inst+0x128, gn.raw); g.wf32(g.inst+0x12c, gn.raw)   # snap EXACT bearing
        gn.snap_elev(); time.sleep(0.15)                             # snap EXACT elevation
        g.wpm(g.inst+0x138, struct.pack("<i", gn.gun_idx))
        if not gn.canfire(): print("  [%s] WARN: not CanFire at fire time" % gn.name)
        g.main_call(gn.M['fcg'][0], g.inst, gn.M['fcg'][1])
        print("  [%s] SHELL AWAY  rot=%.2f elev=%.2f  (range %.2f km, %d chg, %s)" %
              (gn.name, g.bearing(), g.rf32(gn.gun+0xb4), gn.rng, gn.C_CHG, gn.SHELL), flush=True)
        gn.ready=False; remaining.remove(gn); fired.append(gn)
        replenish_charges(g, gn.M)             # buy back the charges this shot spent (keeps the powder inventory full)
    for gn in remaining: print("  [%s] never readied in time -> skip" % gn.name)
    return fired

# ---------------- dynamic targeting (subprocess; runs while we are NOT main-calling) ----------------
def cap(path, args=(), env=None, timeout=None):
    e=dict(os.environ)
    if env: e.update(env)
    try:
        return subprocess.run([PY,path]+[str(a) for a in args], env=e, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as ex:
        class _R: pass
        r=_R(); so=ex.stdout
        r.stdout=(so.decode(errors="ignore") if isinstance(so,(bytes,bytearray)) else (so or "")); r.stderr="[TIMEOUT]"; r.returncode=-9
        return r
def scan():
    r=cap(os.path.join(SCR,"scan_artillery.py"))
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("ARTILLERY_LIVE:"): return set(x for x in ln.split(":",1)[1].split(",") if x)
    return set()
def scan_live_enemies():
    """READ-ONLY list of live enemy IDs (any 'Enemy' icon, hp>0). Draws nothing -> no line-drawing sound."""
    r=cap(os.path.join(SCR,"scan_enemies.py"))
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("ENEMIES_LIVE:"): return [x for x in ln.split(":",1)[1].split(",") if x]
    return []
def _clear_shot():
    for f in ("_shot.txt","_target.txt"):
        try: os.remove(os.path.join(SCR,f))
        except Exception: pass
def _read_shot():
    try:
        sd=open(os.path.join(SCR,"_shot.txt")).read().split()
        bearing,rng,shell=float(sd[0]),float(sd[1]),(sd[2] if len(sd)>2 else "HE")
        picked=open(os.path.join(SCR,"_target.txt")).read().strip()
        return (picked,bearing,rng,shell)
    except Exception:
        return (None,None,None,None)
def pick_target(excluded, mode="ARTILLERY"):
    """Return (id, bearing, range, shell) for the next target, or (None,...) if none.
       ARTILLERY: wait for a fresh (untargeted) live artillery spawn, honoring IRN_EXCLUDE.
       RANDOMENEMY: draw immediately; retry to avoid re-picking an already-engaged target (draw doesn't dedupe)."""
    if mode in ("ARTILLERY","ARTY"):
        fresh=set()
        for _ in range(24):                   # up to ~6 min for the slow respawn (~1 / 1-2 min)
            live=scan(); fresh=live-set(excluded)
            if fresh: break
            time.sleep(15)
        if not fresh: return (None,None,None,None)
        _clear_shot()
        cap(os.path.join(SCR,"draw_from_player.py"), ["ARTILLERY"], env={"IRN_EXCLUDE":",".join(excluded)}, timeout=90)
        return _read_shot()
    # RANDOMENEMY / any-enemy: READ-ONLY scan for a fresh live enemy, then draw it ONCE.
    # (Never draw a line just to TEST freshness -- that was the line-drawing-spam stall.)
    t_end=time.time()+300; empties=0            # wait up to ~5 min for a respawn before giving up
    while time.time()<t_end:
        live=scan_live_enemies()
        fresh=[e for e in live if e not in excluded]
        if not fresh and live and empties>=2:   # enemies ARE alive but all recently engaged -> re-engage any live one so a 100-mission run never starves
            fresh=list(live)
        if fresh:
            pick=random.choice(fresh)
            _clear_shot()
            cap(os.path.join(SCR,"draw_from_player.py"), [pick], env={"IRN_EXCLUDE":",".join(excluded)}, timeout=90)
            r=_read_shot()
            if r[0] is not None: return r
            excluded.append(pick); empties=0    # couldn't draw this one (e.g. just died) -> skip it and rescan
        else:
            empties+=1; time.sleep(12)          # no fresh enemy right now -> wait QUIETLY for a respawn (NO line drawing)
    return (None,None,None,None)

# ---------------- pipeline ----------------
def main():
    _a1=sys.argv[1] if len(sys.argv)>1 else ""
    N=int(_a1) if _a1.isdigit() else 4
    MODE=os.environ.get("IRN_TARGET_MODE","ARTILLERY").upper()      # ARTILLERY (default) | RANDOMENEMY
    print("=== PARALLEL PIPELINED ROUND-ROBIN  x%d  target=%s  (pre-stage both guns; fire = rotate only) ===\n" % (N,MODE), flush=True)
    g=G.Ghost(); g.focus_game(); g.resolve(); g.ensure_executor()
    F=g.F
    _omc=g.main_call
    def _mc(*a,**k):
        r=_omc(*a,**k)
        for _ in range(8):
            if r[0] is not None: return r
            g.focus_game(); time.sleep(0.15); r=_omc(*a,**k)
        return r
    g.main_call=_mc
    gun_cls=g.get_class("GunController"); drag_cls=g.get_class("DraggableItem")
    slot_cls=g.get_class("RequisitionSlot"); lat_cls=g.get_class("LookAtTarget")
    cyl_cls=g.get_class("CylinderShellSelector"); obj_cls=g.get_class("Object","UnityEngine",g.core)
    M=dict(fcg=meth(g,g.tc,"FireControlledGun",0),
           down=meth(g,lat_cls,"OnClickDown",0), up=meth(g,lat_cls,"OnClickUp",0),
           can=meth(g,gun_cls,"get_CanFire",0), bp=meth(g,gun_cls,"get_ChamberedShellBlueprint",0),
           move1=meth(g,drag_cls,"MoveToSlot",1), att=meth(g,slot_cls,"AttemptRequisition",0),
           insert=meth(g,cyl_cls,"TryInsertShellRuntime",2), gname=meth(g,obj_cls,"get_name",0))
    # powder-charge replenishment context: SHARED PowderChargeInventory (_currentCharges @ +0x58,
    # maxCapacity @ +0x24) refilled +20 per 'PowderCharges' requisition (MoveToSlot + AttemptRequisition)
    _inv=g.find_one("PowderChargeInventory")
    _rcm=g.find_one("RequisitionConsoleManager"); _rslot=g.rptr(_rcm+0x30) if _rcm else 0
    _pcdrag=0
    for _prc in g.find_objects("PunchcardRuntime"):
        _dd=g.rptr(_prc+0x20)
        if _dd and rstr(g, g.rptr(_dd+0x18))=="PowderCharges": _pcdrag=g.rptr(_prc+0x28); break
    M['pc']={'inv':_inv, 'max':(g.ru32(_inv+0x24) or 100) if _inv else 100, 'drag':_pcdrag,
             'itemslot':g.rptr(_rslot+0xa0) if _rslot else 0, 'slot':_rslot}
    print("powder: inventory=%d/%d  PowderCharges draggable=%x" %
          (g.ru32(_inv+0x58) if _inv else -1, M['pc']['max'], _pcdrag), flush=True)
    replenish_charges(g, M)                # top up powder up-front so the first loads are never charge-starved (a new game can start low)
    print("  powder after startup top-up: %d/%d" % (g.ru32(_inv+0x58) if _inv else -1, M['pc']['max']), flush=True)
    A=Gun(g,M,"GunLeft"); B=Gun(g,M,"GunRight"); guns=[A,B]
    _only=os.environ.get("IRN_ONLY_GUN","").strip()      # restrict to one gun for focused tests
    if _only: guns=[gn for gn in guns if gn.name==_only] or guns
    print("guns: %s\n" % ", ".join("%s idx=%d"%(gn.name,gn.gun_idx) for gn in guns), flush=True)
    for gn in guns:                          # the cylinder MODEL file is written ONLY by revolver_load, so after any prior run it
        try: os.remove(gn.MODEL_FILE)        # is several shots STALE (post-fire consumption is tracked only in memory). Wipe it at
        except Exception: pass               # startup so the first mission rebuilds the model from the ACTUAL cylinder (occ + goname)
        gn.model=None                        # via revolver_load, instead of "waiting to ram" a shell the file claims but was fired.
    print("  [startup] cylinder model files wiped -> first mission rebuilds from the actual cylinder state", flush=True)

    # ---- STAGE-ONLY test: deterministically validate PARALLEL readying (no fire, no artillery needed) ----
    if sys.argv[1:2] and sys.argv[1].upper()=="STAGE":
        print("=== STAGE-ONLY TEST: pre-stage BOTH guns IN PARALLEL, no fire ===", flush=True)
        tspecs=[(108.0,7.5,"HE"), (96.0,9.0,"HE")]      # two fixed cards (bearing irrelevant until fire)
        for gn,(brg,rng,sh) in zip(guns, tspecs):
            gn.ok=False; gn.ready=False; gn.rng=rng
            print("  [%s] fixed card bearing=%.1f range=%.2f shell=%s" % (gn.name,brg,rng,sh))
            gn.ok=gn.compute_card(brg,rng,3,sh)
        ts=time.time(); stage([gn for gn in guns if gn.ok])
        print("\n>>> STAGED both guns in %.1fs:" % (time.time()-ts))
        for gn in guns:
            print("    [%s] ready=%s CanFire=%s elev=%.2f(->%.2f) charge=%d" %
                  (gn.name, gn.ready, gn.canfire(), gn.g.rf32(gn.gun+0xb4), gn.C_ELEV, gn.chambered_charge()))
        print("    bearing left UNTOUCHED -> only 'rotate to bearing + fire' remains for each gun's turn.")
        return

    # ============ PER-GUN PIPELINE ============
    # Each gun starts its NEXT mission (target -> card -> cylinder cycle to the right shell -> chamber ->
    # charge) the INSTANT it fires, so the reload + shell-selection overlap the gun's leveling/elevation
    # AND the other gun's shot + its own recovery. Only the shared turret bearing is serial (a ready gun fires).
    t0=time.time(); excluded=[]; engaged=[]; shots=0
    for gn in guns: gn.phase="IDLE"; gn.ready=False; gn.stocked=False
    LOAD_ELEV=g.rf32(g.inst+0x44) or 0.0             # loading elevation (level) -- the reload needs the gun HERE, not raised

    # ---- steam-valve auto-management ----
    # The turret runs "under pressure": ValveControllers randomly leak (currentDamage01 @ +0xe0 -> 1.0), and a leaking
    # valve BLOCKS its pressure system's mechanism (ShellRammer/Cylinder/Charges/Elevation/RotationHydrolics) -- so the
    # ram/cycle silently stops responding to triggers. Each valve's lever is its dial (+0x30, a DialInteractable);
    # turning it to fixedValue (+0x38, =0) reseals it (verified: dial->broken=damage 1.0, dial->fixed=damage 0.0).
    VALVES=[]
    for _v in g.find_objects("ValveController"):
        _d=g.rptr(_v+0x30)
        if _d: VALVES.append((_v, _d, g.rf32(_v+0x38) or 0.0, g.rf32(_v+0x3c) or 100.0))
    print("steam valves: %d  (auto-reseal any that leak so the autoloader never pressure-stalls)" % len(VALVES), flush=True)
    def reseal_valves():
        n=0
        for _v,_d,_fx,_bk in VALVES:
            if (g.rf32(_v+0xe0) or 0.0) > 0.03:          # leaking -> turn its dial back to sealed
                g.set_dial(_d, _fx); n+=1
        if n: print("  >> RESEALED %d leaking steam valve(s)" % n, flush=True)
        return n
    g.reseal_valves=reseal_valves                        # expose so the blocking reload waits can reseal too
    _VTEST=os.environ.get("IRN_VALVE_TEST","")=="1"; _vleak=[time.time()]
    def maybe_induce_leak():                             # IRN_VALVE_TEST=1: spring a random leak now and then to exercise the auto-reseal
        if not _VTEST or not VALVES or time.time()-_vleak[0]<16: return
        _v,_d,_fx,_bk=random.choice(VALVES); g.set_dial(_d,_bk); _vleak[0]=time.time()
        print("  >> [TEST] sprang a steam leak (dial 0x%x -> %.0f)" % (_d,_bk), flush=True)

    def start_mission(gn):
        """Pick next target, card it, and BEGIN this gun's reload + leveling immediately (overlaps everything)."""
        picked,bearing,rng,shell=pick_target(excluded, MODE)
        if picked is None: gn.phase="DONE"; return
        excluded.append(picked); gn.target=picked; gn.rng=rng
        del excluded[:-12]                              # keep only the last 12 picks -> a long endurance run never exhausts the live-enemy pool
        gn.compute_card(bearing,rng,3,shell)            # always True (fire-MAX fail-safe)
        gn.ready=False; gn.stocked=False; gn.last_click=0.0
        gn._selnote=False; gn._levelt=None; gn._cyclog=False; gn._rot=0
        if gn.canfire() and (gn.chambered_charge()!=gn.C_CHG or gn.chambered_type()!=gn.SHELL):
            print("  [%s] wrong load -> discharging to reload" % gn.name, flush=True)
            g.wpm(g.inst+0x138, struct.pack("<i", gn.gun_idx)); g.main_call(gn.M['fcg'][0], g.inst, gn.M['fcg'][1])
            t1=time.time()
            while gn.canfire() and time.time()-t1<6: time.sleep(0.1)
            time.sleep(2.0)
        gn.elevated=False                                # elevate LATER -- the instant the shell is chambered (per-gun)
        gn.phase="RELOAD"
        print("  [%6.1fs] [%s] MISSION START -> %s  range=%.2f km  shell=%s  (cylinder cycling to the shell now)" %
              (time.time()-t0, gn.name, picked, rng, gn.SHELL), flush=True)

    def advance(gn):                                     # ONE non-blocking reload step
        if gn.phase!="RELOAD": return
        if not gn.stocked:
            if gn.canfire():
                gn.stocked=True                          # already loaded with the correct round
            elif gn.chambered():
                gn.stocked=True                          # a shell is already chambered (mid-load) -> finish the charges/close via prep_tick
            else:
                want=gn.SHELL
                if gn.model is None: gn.model=gn.rev_loadmodel() or [None]*6
                if gn.rev_steady():
                    # breech OPEN + SETTLED -> AUTHORITATIVE goname check: finalize, or correct any leveling-rotation drift.
                    bt=gn.breech_type_steady()               # real shell at the breech (crash-safe only when steady)
                    if bt==want:
                        gn.model[0]=want; gn.stocked=True    # confirmed at breech -> prep_tick rams (loadButton only lives when level)
                    elif want in [m for m in gn.model if m] and getattr(gn,"_rot",0)<=12:
                        if gn.rev_pull(): gn.model[:]=gn.model[1:]+gn.model[:1]; gn._rot=getattr(gn,"_rot",0)+1
                    else:                                    # want not in cylinder / drifted too far -> stock fresh (tops the cylinder up)
                        if not gn.revolver_load(want): gn.phase="IDLE"; return
                        gn.stocked=True; gn._rot=0
                    return
                # NOT steady yet -> the gun is still LEVELING, but the cylinder lever (moveBtn) is LIVE during the descent
                # (the game's own gate, which self-disables at the one unsafe instant, reloadState=2). Rotate NOW so the
                # cylinder cycling fully OVERLAPS leveling. The model advances optimistically; the rev_steady() branch above
                # goname-verifies + corrects it the instant the breech opens -> overlap WITH no state desync.
                if gn.model[0]!=want and want in [m for m in gn.model if m] and gn.move_active() and getattr(gn,"_rot",0)<=8:
                    if gn.rev_pull_live():
                        gn.model[:]=gn.model[1:]+gn.model[:1]; gn._rot=getattr(gn,"_rot",0)+1
                        if not getattr(gn,"_cyclog",False):
                            print("  [%6.1fs] [%s] cylinder cycling toward %s at elev=%.1f (MID-LEVELING overlap)" %
                                  (time.time()-t0, gn.name, want, gn.g.rf32(gn.gun+0xb4)), flush=True); gn._cyclog=True
                return
        if not gn.stocked: return
        if not gn.ready:
            gn.prep_tick()                               # ram + charge (the ram/loadButton only goes live once the gun is level)
            if gn.canfire(): gn.ready=True
        if gn.ready and not gn.elevated:                 # round FULLY LOADED -> elevate to firing angle (per-gun, independent)
            gn.set_gun_elev(gn.C_ELEV); gn.elevated=True
            print("  [%6.1fs] [%s] loaded -> elevating to %.1f (not waiting for the other gun)" %
                  (time.time()-t0, gn.name, gn.C_ELEV), flush=True)
            gn.phase="READY"

    for gn in guns: start_mission(gn)                    # prime both guns
    while shots<N:
        maybe_induce_leak(); reseal_valves()              # pressure mgmt: (test) spring leaks + reseal any leak so ram/cycle/charge never blocks
        for gn in guns: advance(gn)                       # advance ALL reloads (cylinder cycles during leveling, etc.)
        # AIM the shared turret at the NEXT-to-fire gun's bearing AS SOON AS its card exists -- this overlaps
        # that gun's load + elevation, so the turret does NOT wait for elevation to finish before rotating.
        prepping=[gn for gn in guns if gn.phase in ("RELOAD","READY")]
        if prepping:
            # aim at the gun that will FIRE SOONEST (by load progress), NOT the nearest bearing. Otherwise the turret
            # pre-aims at a far/slow gun (e.g. one still leveling from a high-elevation shot), the OTHER gun finishes
            # first, the turret diverts to fire it, then swings back -- the wasted "ping-pong" motion. Bearing distance
            # is only the tie-breaker among equally-ready guns. eta: 0=ready+aimed,1=ready+elevating,2=charging,3=cycling.
            def _eta(x):
                if x.phase=="READY": return 0 if x.elev_done() else 1
                return 2 if x.stocked else 3
            nxt=min(prepping, key=lambda x: (_eta(x), abs(((g.bearing() or 0)-x.raw+180)%360-180)))
            g.aim_bearing(nxt.raw)
        # FIRE the first gun that is loaded + elevated AND the bearing has already arrived
        fireable=[gn for gn in guns if gn.phase=="READY" and gn.elev_done()
                  and abs(((g.bearing() or 0)-gn.raw+180)%360-180)<0.5]
        if fireable:
            gn=fireable[0]
            g.wf32(g.inst+0x128, gn.raw); g.wf32(g.inst+0x12c, gn.raw)       # snap EXACT bearing
            gn.snap_elev(); time.sleep(0.1)                                  # snap EXACT elevation
            g.wpm(g.inst+0x138, struct.pack("<i", gn.gun_idx))
            if not gn.canfire(): print("  [%s] WARN: not CanFire at fire time" % gn.name, flush=True)
            g.main_call(gn.M['fcg'][0], g.inst, gn.M['fcg'][1])
            shots+=1
            print("  [%6.1fs] [%s] SHELL AWAY #%d  rot=%.2f elev=%.2f  (range %.2f km, %d chg, %s)" %
                  (time.time()-t0, gn.name, shots, g.bearing(), g.rf32(gn.gun+0xb4), gn.rng, gn.C_CHG, gn.SHELL), flush=True)
            engaged.append(gn.target); cap(os.path.join(SCR,"remove_line.py"))
            replenish_charges(g, gn.M)
            if shots % 10 == 0 or shots==N:                                  # endurance heartbeat: rate + powder headroom
                _inv=M['pc']['inv']; _pw=g.ru32(_inv+0x58) if _inv else -1; _el=time.time()-t0
                print("  ====== progress %d/%d shots in %.0fs (avg %.1fs/shot)  powder=%d/%d ======" %
                      (shots, N, _el, _el/max(shots,1), _pw, M['pc']['max']), flush=True)
            g.wf32(gn.gun+0xb8, LOAD_ELEV); g.wf32(gn.gun+0xf0, LOAD_ELEV)   # DESIRED=level only -> gun lowers NORMALLY (servo, immersive)
            if gn.model: gn.model[0]=None                 # breech round consumed -> next mission cycles to the next shell
            gn.phase="IDLE"
            if shots<N: start_mission(gn)                 # next mission's card exists immediately -> turret starts rotating to it next iteration
        if all(gn.phase=="DONE" for gn in guns):
            print("  both guns out of targets -> stopping", flush=True); break
        time.sleep(0.12)

    if MODE in ("ARTILLERY","ARTY"):
        print("\nconfirming kills (shells in flight) ...", flush=True)
        dead=[]
        for _ in range(12):
            final=scan(); dead=[t for t in engaged if t not in final]
            if len(dead)>=len(engaged): break
            time.sleep(4)
        print("\n"+"="*64)
        print(">>> PARALLEL ROUND-ROBIN DONE in %.1fs: fired %d, CONFIRMED %d/%d DEAD" %
              (time.time()-t0, len(engaged), len(dead), len(engaged)))
        print("    killed: %s" % sorted(dead))
        miss=[t for t in engaged if t not in dead]
        if miss: print("    not confirmed dead: %s" % miss)
    else:
        print("\n"+"="*64)
        print(">>> PARALLEL PIPELINE DONE in %.1fs: fired %d shots (parallel-staged, serial-fired)" %
              (time.time()-t0, len(engaged)))
        print("    targets: %s" % engaged)

if __name__=="__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc()
