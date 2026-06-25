"""
IRON NEST - autonomous end-to-end fire mission.

Given a BEARING and RANGE (read off the map, like a human gunner), this runs the
ENTIRE firing process with no operator in the loop:

  1. Punch range + powder + bearing + HE into the in-game ArtilleryComputer and press
     CALCULATE  -> the game produces a fire-mission CARD with the exact elevation.
  2. Read the card (rotation / elevation / charges / shell).
  3. LOAD the gun: buy an HE shell, then drive the real breech buttons to chamber the
     shell + ram the card's number of charges + close the breech.
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
    rc  = [r for r in g.find_objects("ArtilleryReloadController") if gn(g.rptr(r+0x68))=="GunLeft"][0]
    cyl = [c for c in g.find_objects("CylinderShellSelector") if g.rptr(c+0x40)==rc][0]
    pc  = [p for p in g.find_objects("PowderChargeController") if g.rptr(p+0x48)==rc][0]
    gun = g.rptr(rc+0x68); ac = g.computer; pr = g.printer
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

    print("focus=%s  | MISSION: bearing=%.1f  range=%.2f km  powder=%d\n" % (foc, BEARING, RANGE, POWDER))

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

    # ================= PHASE 2: LOAD (buy the icon-picked shell + card charges) =================
    print("=== PHASE 2: load %s + %d charges ===" % (SHELL, C_CHG))
    # clear a leftover load that has the wrong charge
    if canfire() and chambered_charge() != C_CHG:
        print("  wrong charge chambered -> discharging to reload"); g.main_call(m_fcg[0], g.inst, m_fcg[1])
        t0=time.time()
        while canfire() and time.time()-t0<6: time.sleep(0.1)
        time.sleep(2.0)
    # >>> kick off the turret traverse NOW so it slews CONCURRENTLY with the load
    print("  >> traversing to %.1f concurrently with loading" % C_BEAR)
    g.aim_bearing(raw); g.set_elevation(C_ELEV)   # elevation target queued; applies once the breech locks
    if not canfire():
        if g.rb(cyl+0x88) == 0:   # buy the icon-picked shell (HEShell / APShell) into the cylinder
            card_name = SHELL + "Shell"
            sh = 0
            for prc in g.find_objects("PunchcardRuntime"):
                dd = g.rptr(prc+0x20)
                if dd and rstr(g.rptr(dd+0x18)) == card_name: sh = g.rptr(prc+0x28); break
            rcm = g.find_one("RequisitionConsoleManager"); slot = g.rptr(rcm+0x30); itemslot = g.rptr(slot+0xa0)
            print("  buying %s" % card_name); g.main_call(m_move1[0], sh, itemslot, m_move1[1]); time.sleep(0.6)
            g.main_call(m_att[0], slot, m_att[1]); time.sleep(2.0)
        mv = 0; t0 = time.time()
        while not canfire() and time.time()-t0 < 90:
            if not chambered() and active(b_cylLoad()): print("  chamber %s" % SHELL); press(b_cylLoad()); continue
            if not chambered() and g.rb(cyl+0x88)==0 and active(b_cylMove()) and mv<8: mv+=1; press(b_cylMove()); continue
            if state()=="SelectPowderCharge" and g.ru32(pc+0x80) < C_CHG:
                cb = [b for b in b_charges() if active(b)]
                if cb: press(cb[0]); continue
            if active(b_pwdLoad()) and g.ru32(pc+0x80) >= C_CHG: print("  ram %d charges" % C_CHG); press(b_pwdLoad()); continue
            if active(b_adv()): press(b_adv()); continue
            time.sleep(0.15)
    bp_final = g.main_call(m_bp[0], gun, m_bp[1])[0]
    print("  LOADED: shell=%s charge=%d CanFire=%s\n" % (shtype(goname(bp_final)) if bp_final else "none", chambered_charge(), canfire()))

    # ================= PHASE 3: TRAVERSE + ELEVATE (exact) =================
    print("=== PHASE 3: finalize aim (traverse ran during the load) ===")
    g.slew_to(raw, tol=0.4, timeout=20)          # ensure arrived (usually already there from the concurrent slew)
    g.wf32(g.inst+0x128, raw); g.wf32(g.inst+0x12c, raw)   # snap EXACT bearing
    g.set_elevation(C_ELEV)
    t0 = time.time()
    while time.time()-t0 < 45:
        if abs((g.rf32(gun+0xb4) or 0) - C_ELEV) < 0.25: break
        time.sleep(0.2)
    g.wf32(gun+0xb4, C_ELEV); g.wf32(gun+0xb8, C_ELEV)     # snap EXACT elevation
    time.sleep(0.3)
    print("  turret rotation=%.2f (->%.2f)  gun elevation=%.2f (->%.2f)\n" % (g.bearing(), raw, g.rf32(gun+0xb4), C_ELEV))

    # ================= PHASE 4: FIRE =================
    print("=== PHASE 4: FIRE ===")
    g.wpm(g.inst+0x138, struct.pack("<i", 0))    # controlled gun = GunLeft
    if not canfire(): print("  WARN: gun not CanFire");
    g.main_call(m_fcg[0], g.inst, m_fcg[1])
    print("  SHELL AWAY at rotation=%.2f elevation=%.2f (range %.2f km, %d charges, %s)" % (
        g.bearing(), g.rf32(gun+0xb4), RANGE, C_CHG, SHELL))
    print("\n>>> FIRE MISSION COMPLETE.")

if __name__ == "__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc()
