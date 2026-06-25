"""
IRON NEST - autonomous end-to-end fire mission.

Given a BEARING and RANGE (read off the map, like a human gunner), this runs the
ENTIRE firing process with no operator in the loop:

  1. Punch range + powder + bearing + HE into the in-game ArtilleryComputer and press
     CALCULATE  -> the game produces a fire-mission CARD with the exact elevation.
  2. Read the card (rotation / elevation / charges / shell).
  3. LOAD via the REVOLVER: stock a 3xHE+3xAP mix once (buy+lever, persisted), rotate-select
     the icon's shell to the breech, then chamber + ram the card's charges + close the breech.
  4. TRAVERSE to the card bearing and ELEVATE to the card elevation (exact).
  5. FIRE.

Everything is driven through the game's own controls/calculation, so on the
zero-dispersion gun the shot lands on the bearing/range you gave.

Usage:
    python ironnest_fire_mission.py <bearing> <range> [powder=3]
    e.g.  python ironnest_fire_mission.py 51.0 3.31
"""
import sys, time, struct
import ironnest_ghost as G

def main():
    if len(sys.argv) < 3:
        print("usage: ironnest_fire_mission.py <bearing> <range> [powder=3]"); return
    BEARING = float(sys.argv[1]); RANGE = float(sys.argv[2])
    POWDER  = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    import os
    SHELL = os.environ.get("IRN_SHELL","HE").upper()      # which shell to load via the revolver
    if SHELL not in ("HE","AP"): SHELL = "HE"
    GUN = os.environ.get("IRN_GUN","GunLeft").strip() or "GunLeft"   # which gun: GunLeft / GunRight

    g = G.Ghost(); foc = g.focus_game(); g.resolve(); g.ensure_executor()
    F = g.F
    import time as _t
    _omc=g.main_call
    def _mc(*a,**k):
        r=_omc(*a,**k)
        for _ in range(8):
            if r[0] is not None: return r
            g.focus_game(); _t.sleep(0.15); r=_omc(*a,**k)
        return r
    g.main_call=_mc
    def rstr(p):
        if not p: return ""
        n = g.ru32(p+0x10); return g.rpm(p+0x14, n*2).decode("utf-16-le","ignore") if 0<n<400 else ""
    def meth(cls, name, argc):
        mi = g.rc(F["il2cpp_class_get_method_from_name"], cls, g.cstr(320, name), argc); return g.rptr(mi), mi
    def gn(gp): return rstr(g.rptr(gp+0x20))

    # ---- instances ----
    _rcs = [r for r in g.find_objects("ArtilleryReloadController") if gn(g.rptr(r+0x68))==GUN]
    if not _rcs:
        print("gun %r not found (have %s)" % (GUN, sorted({gn(g.rptr(r+0x68)) for r in g.find_objects("ArtilleryReloadController")}))); return
    rc  = _rcs[0]
    cyl = [c for c in g.find_objects("CylinderShellSelector") if g.rptr(c+0x40)==rc][0]
    pc  = [p for p in g.find_objects("PowderChargeController") if g.rptr(p+0x48)==rc][0]
    gun = g.rptr(rc+0x68); ac = g.computer; pr = g.printer
    gun_idx = g.guns.index(gun) if gun in g.guns else 0      # controlled-gun index (shared turret, per-gun fire)
    g.wpm(g.inst+0x138, struct.pack("<i", gun_idx))          # control THIS gun for the WHOLE mission (buy/load land on it)
    def set_gun_elev(deg):                                   # INDEPENDENT per-gun elevation (NOT the turret-level / other gun)
        lo=g.rf32(g.inst+0x44) or 0.0; hi=g.rf32(g.inst+0x48) or 60.0; deg=max(lo,min(hi,deg))
        g.wf32(gun+0xb8, deg); g.wf32(gun+0xf0, deg)         # this gun's DesiredElevationAngle + internalDesiredElevation
    lst = g.rptr(rc+0x28); it2 = g.rptr(lst+0x10)
    names = {i: rstr(g.rptr(g.rptr(it2+0x20+i*8)+0x10)) for i in range(g.ru32(lst+0x18))}

    gun_cls = g.get_class("GunController"); drag_cls = g.get_class("DraggableItem")
    slot_cls = g.get_class("RequisitionSlot"); lat_cls = g.get_class("LookAtTarget")
    m_fcg = meth(g.tc, "FireControlledGun", 0)
    m_move1 = meth(drag_cls, "MoveToSlot", 1); m_att = meth(slot_cls, "AttemptRequisition", 0)
    m_down = meth(lat_cls, "OnClickDown", 0); m_up = meth(lat_cls, "OnClickUp", 0)
    m_can = meth(gun_cls, "get_CanFire", 0); m_bp = meth(gun_cls, "get_ChamberedShellBlueprint", 0)

    def canfire():  return ((g.main_call(m_can[0], gun, m_can[1])[0] or 0) & 0xff) == 1
    def chambered():return g.rptr(rc+0x38) != 0
    def state():    return names.get(g.ru32(rc+0x48), "?")
    def active(b):  return bool(b) and g.rb(b+0xa0) == 1
    def press(b):
        g.main_call(m_down[0], b, m_down[1]); time.sleep(0.04); g.main_call(m_up[0], b, m_up[1])
        t0 = time.time()
        while active(b) and time.time()-t0 < 3: time.sleep(0.03)
    def chambered_charge():
        bp = g.main_call(m_bp[0], gun, m_bp[1])[0]
        return g.ru32(bp+0x28) if bp else -1
    # button refs
    b_cylLoad = lambda: g.rptr(cyl+0x50)
    b_cylMove = lambda: g.rptr(cyl+0x60)
    b_pwdLoad = lambda: g.rptr(pc+0x40)
    def b_adv():
        sd = g.rptr(it2+0x20 + g.ru32(rc+0x48)*8); return g.rptr(sd+0x30) if sd else 0
    def b_charges():
        cl = g.rptr(pc+0x20); it = g.rptr(cl+0x10); n = g.ru32(cl+0x18) if cl else 0
        return [g.rptr(it+0x20+i*8) for i in range(min(n,8))] if it else []

    print("focus=%s  | MISSION[%s]: bearing=%.1f  range=%.2f km  powder=%d\n" % (foc, GUN, BEARING, RANGE, POWDER))

    # ================= PHASE 1: CALCULATOR -> CARD =================
    print("=== PHASE 1: punch the calculator, press CALCULATE ===")
    rangeDial = g.rptr(ac+0x28); powderDial = g.rptr(ac+0x38); calcBtn = g.rptr(ac+0x48)
    bearingDial = g.rptr(pr+0x40); shellDial = g.rptr(pr+0x48)
    sl = g.rptr(pr+0xb8); items = g.rptr(sl+0x10); n = g.ru32(sl+0x18) if sl else 0
    he_idx = next((i for i in range(min(n,16)) if rstr(g.rptr(g.rptr(items+0x20+i*8)+0x18))=="HE"), 3)
    ap_idx = next((i for i in range(min(n,16)) if rstr(g.rptr(g.rptr(items+0x20+i*8)+0x18))=="AP"), 1)
    shell_idx = ap_idx if SHELL=="AP" else he_idx        # compute the card with the requested shell

    def calc(powder):
        g.set_dial(rangeDial, RANGE); g.set_dial(powderDial, powder)
        g.set_dial(bearingDial, BEARING); g.set_dial(shellDial, shell_idx); time.sleep(0.4)
        press(calcBtn); time.sleep(2.2)
        return g.rf32(ac+0xb4), g.rb(ac+0xa9)   # lastValidElevation, errorActive
    elev, err = calc(POWDER)
    # if this charge can't reach the range, walk charges up/down
    if err or elev <= 0:
        for trial in [POWDER+1, POWDER+2, POWDER-1, POWDER+3, 6, 5, 4, 2, 1]:
            if 1 <= trial <= 6:
                elev, err = calc(trial)
                if not err and elev > 0: POWDER = trial; break
    def tmptext(p): return rstr(g.rptr(p+0xe0)) if p else ""
    cards = g.find_objects("FireMissionCard")
    card = {}
    if cards:
        c = cards[0]
        card = dict(distance=tmptext(g.rptr(c+0x20)), bearing=tmptext(g.rptr(c+0x28)),
                    elevation=tmptext(g.rptr(c+0x30)), powder=tmptext(g.rptr(c+0x38)),
                    shell=tmptext(g.rptr(c+0x40)))
    import re
    def num(s):
        m = re.search(r"-?\d+\.?\d*", s or ""); return float(m.group()) if m else None
    C_BEAR = num(card.get("bearing")) if card.get("bearing") else BEARING
    C_ELEV = num(card.get("elevation")) if card.get("elevation") else elev
    C_CHG  = int(num(card.get("powder")) or POWDER)
    print("  CARD -> rotation=%.1f  elevation=%.2f  charges=%d  shell=%s\n" % (C_BEAR, C_ELEV, C_CHG, card.get("shell","HE")))
    if (C_ELEV or 0) <= 0 or err:
        print("  !! OUT OF RANGE: no charge (up to 6) yields a valid firing solution for %.2f km." % RANGE)
        print("     Aborting - not wasting a shell; this target is beyond max effective range.\n")
        return
    raw = ((-C_BEAR + 180) % 360) - 180   # compass bearing -> turret raw angle (compass = -raw)

    obj_cls = g.get_class("Object","UnityEngine",g.core); m_gname = meth(obj_cls,"get_name",0)
    def goname(o):
        r=g.main_call(m_gname[0],o,m_gname[1])[0]; return rstr(r) if r else ""
    def shtype(nm):
        if not nm: return "--"
        if "HCHE" in nm: return "HCHE"
        if "HE" in nm: return "HE"
        if "AP" in nm: return "AP"
        return "--"

    # ---- REVOLVER loader: stock-once / fire-many, persisted to _cylinder_model.txt next to this script ----
    MODEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cylinder_model_%s.txt" % GUN)
    def occ_list():
        bl=g.rptr(cyl+0x30); bit=g.rptr(bl+0x10); nb=g.ru32(bl+0x18) if bl else 0
        return [bool(g.rptr(bit+0x20+i*8)) for i in range(nb)] if 0<nb<=12 else []
    def rev_steady():
        sb=g.rb(cyl+0x88); return g.ru32(rc+0x48)==3 and sb is not None
    def rev_buy(typ):
        cn=typ+"Shell"; sh=0
        for prc in g.find_objects("PunchcardRuntime"):
            dd=g.rptr(prc+0x20)
            if dd and rstr(g.rptr(dd+0x18))==cn: sh=g.rptr(prc+0x28); break
        if not sh: return False
        rcm=g.find_one("RequisitionConsoleManager"); slot=g.rptr(rcm+0x30); itemslot=g.rptr(slot+0xa0)
        g.main_call(m_move1[0], sh, itemslot, m_move1[1]); time.sleep(0.7)
        g.main_call(m_att[0], slot, m_att[1]); time.sleep(2.0)
        return g.rpm(rc+0x48,4) is not None
    def rev_pull():
        if not rev_steady(): return False
        mb=g.rptr(cyl+0x60)
        if not mb or g.rb(mb+0xa0)!=1: return False
        g.main_call(m_down[0],mb,m_down[1]); time.sleep(0.12); g.main_call(m_up[0],mb,m_up[1]); time.sleep(1.5)
        return g.rpm(rc+0x48,4) is not None
    def rev_loadmodel():
        try:
            parts=open(MODEL_FILE).read().strip().split(",")
            if len(parts)>=6: return [(p if p in ("HE","AP","HCHE") else None) for p in parts[:6]]
        except Exception: pass
        return None
    cyl_cls = g.get_class("CylinderShellSelector"); m_insert = meth(cyl_cls, "TryInsertShellRuntime", 2)
    _slotbuf = G.VirtualAllocEx(g.h, None, 8, 0x3000, 0x04)
    _sl = g.rptr(pr+0xb8); _items = g.rptr(_sl+0x10); _n = g.ru32(_sl+0x18) if _sl else 0
    SHELLDEF = {rstr(g.rptr(g.rptr(_items+0x20+i*8)+0x18)): g.rptr(_items+0x20+i*8) for i in range(min(_n,16))}
    def rev_insert(typ):                     # GUN-SPECIFIC stock: insert a shell straight into THIS cylinder; returns filled slot or -1
        if not rev_steady() or typ not in SHELLDEF: return -1
        before=occ_list()
        g.wpm(_slotbuf, b"\0"*8); g.main_call(m_insert[0], cyl, SHELLDEF[typ], _slotbuf, m_insert[1]); time.sleep(0.5)
        if g.rpm(rc+0x48,4) is None: return -1
        after=occ_list()
        for i in range(min(len(before),len(after),6)):
            if (not before[i]) and after[i]: return i
        return -1
    def revolver_load(want):
        t0=time.time()
        while not rev_steady() and time.time()-t0 < 90: time.sleep(0.5)   # gun auto-cycles back to BreechOpen after a shot (~30-90s)
        if not rev_steady():
            print("  revolver: gun not back to BreechOpen after 90s -> skip"); return
        model=[None]*6; o=occ_list(); pm=rev_loadmodel(); stocked=False
        if pm is not None and len(o)==6:
            pmo=[x is not None for x in pm]
            if pmo==o: model[:]=pm; stocked=True
            elif pm[0] is not None and ([False]+pmo[1:])==o: model[:]=[None]+pm[1:]; stocked=True
            if stocked and not any(model): stocked=False   # reconciled to all-empty => cylinder truly empty => re-stock the full mix
        if not stocked and not any(o):
            print("  revolver: empty cylinder -> stocking 3xHE + 3xAP via direct insert [%s]" % GUN)
            for typ in ["HE","HE","HE","AP","AP","AP"]:
                slot=rev_insert(typ)
                if slot<0: print("  revolver: insert %s failed" % typ); break
                model[slot]=typ
            stocked=True
        elif not stocked:                       # leftover shells, no model -> read their types (cylinder is steady) to re-sync
            _bl=g.rptr(cyl+0x30); _bit=g.rptr(_bl+0x10); _nb=g.ru32(_bl+0x18) if _bl else 0
            for i in range(min(_nb,6)):
                bp=g.rptr(_bit+0x20+i*8)
                if bp:
                    nm=goname(bp); model[i]=("HCHE" if "HCHE" in nm else "AP" if "AP" in nm else "HE" if "HE" in nm else "?")
            print("  revolver: %d leftover shells -> re-synced model=%s" % (sum(o), [m or "-" for m in model]))
            stocked=True
        if want not in [m for m in model if m] and None in model:   # wanted type not present -> insert a fresh one
            print("  revolver: %s not in stock -> inserting a fresh %s [%s]" % (want,want,GUN))
            slot=rev_insert(want)
            if slot>=0: model[slot]=want
        if want in [m for m in model if m]:     # rotate wanted shell to breech AND settle so the load button engages
            for _ in range(8):
                lb=g.rptr(cyl+0x50)
                if model[0]==want and lb and g.rb(lb+0xa0)==1: break   # want at breech AND load button active
                if not rev_pull(): break
                model[:]=model[1:]+model[:1]
        try: open(MODEL_FILE,"w").write(",".join(m if m else "-" for m in model))
        except Exception: pass
        print("  revolver: stock=%s -> breech=%s" % ([m or "-" for m in model], model[0] or "empty"))

    # ================= PHASE 2: LOAD (REVOLVER: stock mix + rotate-select by icon, then ram charges) =================
    print("=== PHASE 2: REVOLVER-load %s + %d charges ===" % (SHELL, C_CHG))
    # clear a leftover load that has the wrong charge
    if canfire() and chambered_charge() != C_CHG:
        print("  wrong charge chambered -> discharging to reload"); g.main_call(m_fcg[0], g.inst, m_fcg[1])
        t0=time.time()
        while canfire() and time.time()-t0<6: time.sleep(0.1)
        time.sleep(2.0)
    # >>> kick off the turret traverse NOW so it slews CONCURRENTLY with the load
    print("  >> traversing to %.1f concurrently with loading" % C_BEAR)
    g.aim_bearing(raw); set_gun_elev(C_ELEV)   # elevation target queued; applies once the breech locks
    if not canfire():
        revolver_load(SHELL)   # stock-once + rotate-select the icon's shell to the breech (guarded, persisted)
        t0 = time.time()
        while not canfire() and time.time()-t0 < 90:
            if not chambered() and active(b_cylLoad()): print("  chamber %s" % SHELL); press(b_cylLoad()); continue
            if state()=="SelectPowderCharge" and g.ru32(pc+0x80) < C_CHG:
                cb = [b for b in b_charges() if active(b)]
                if cb: press(cb[0]); continue
            if active(b_pwdLoad()) and g.ru32(pc+0x80) >= C_CHG: print("  ram %d charges" % C_CHG); press(b_pwdLoad()); continue
            if g.rb(cyl+0x88)==1 and not chambered(): time.sleep(0.2); continue   # shell at breech not yet chambered -> wait, don't advance past it
            if active(b_adv()): press(b_adv()); continue
            time.sleep(0.15)
    bp_final = g.main_call(m_bp[0], gun, m_bp[1])[0]
    print("  LOADED: shell=%s charge=%d CanFire=%s\n" % (shtype(goname(bp_final)) if bp_final else "none", chambered_charge(), canfire()))

    # ================= PHASE 3: TRAVERSE + ELEVATE (exact) =================
    print("=== PHASE 3: finalize aim (traverse ran during the load) ===")
    g.slew_to(raw, tol=0.4, timeout=20)          # ensure arrived (usually already there from the concurrent slew)
    g.wf32(g.inst+0x128, raw); g.wf32(g.inst+0x12c, raw)   # snap EXACT bearing
    set_gun_elev(C_ELEV)
    t0 = time.time()
    while time.time()-t0 < 45:
        if abs((g.rf32(gun+0xb4) or 0) - C_ELEV) < 0.25: break
        time.sleep(0.2)
    g.wf32(gun+0xb4, C_ELEV); g.wf32(gun+0xb8, C_ELEV)     # snap EXACT elevation
    time.sleep(0.3)
    print("  turret rotation=%.2f (->%.2f)  gun elevation=%.2f (->%.2f)\n" % (g.bearing(), raw, g.rf32(gun+0xb4), C_ELEV))

    # ================= PHASE 4: FIRE =================
    print("=== PHASE 4: FIRE ===")
    g.wpm(g.inst+0x138, struct.pack("<i", gun_idx))    # controlled gun = GUN (this mission's gun)
    if not canfire(): print("  WARN: gun not CanFire");
    g.main_call(m_fcg[0], g.inst, m_fcg[1])
    print("  SHELL AWAY at rotation=%.2f elevation=%.2f (range %.2f km, %d charges, %s)" % (
        g.bearing(), g.rf32(gun+0xb4), RANGE, C_CHG, SHELL))
    print("\n>>> FIRE MISSION COMPLETE.")

if __name__ == "__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc()
