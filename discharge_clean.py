"""Clear leftover chambered rounds (from a mid-run kill) by finishing any mid-charge then discharging,
   leaving both guns at a clean BreechOpen. Reuses the pipeline's proven Gun class."""
import sys, os, time, struct
GHOST=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, GHOST)
import ironnest_ghost as G
import ironnest_parallel_rr as P

g=G.Ghost(); g.focus_game(); g.resolve(); g.ensure_executor()
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
M=dict(fcg=P.meth(g,g.tc,"FireControlledGun",0),
       down=P.meth(g,lat_cls,"OnClickDown",0), up=P.meth(g,lat_cls,"OnClickUp",0),
       can=P.meth(g,gun_cls,"get_CanFire",0), bp=P.meth(g,gun_cls,"get_ChamberedShellBlueprint",0),
       move1=P.meth(g,drag_cls,"MoveToSlot",1), att=P.meth(g,slot_cls,"AttemptRequisition",0),
       insert=P.meth(g,cyl_cls,"TryInsertShellRuntime",2), gname=P.meth(g,obj_cls,"get_name",0))

A=P.Gun(g,M,"GunLeft"); B=P.Gun(g,M,"GunRight")
for gn in [A,B]:
    gn.C_CHG=6; gn.SHELL="HE"; gn.last_click=0.0
    rs=g.ru32(gn.rc+0x48)
    print("[%s] start: reloadState=%d canfire=%s chambered=%s" % (gn.name, rs, gn.canfire(), gn.chambered()))
    if not gn.canfire() and gn.chambered():            # mid-charge -> finish the load so it can be discharged
        t0=time.time()
        while not gn.canfire() and time.time()-t0<45:
            gn.prep_tick(); time.sleep(0.18)
        print("[%s] finished mid-load -> canfire=%s" % (gn.name, gn.canfire()))
    if gn.canfire():                                   # discharge the chambered round to clear the chamber (guns already level at 0.0)
        g.wpm(g.inst+0x138, struct.pack("<i", gn.gun_idx))
        g.main_call(M['fcg'][0], g.inst, M['fcg'][1])
        print("[%s] DISCHARGED" % gn.name)
        time.sleep(2.5)
    else:
        print("[%s] nothing chambered to clear" % gn.name)

print("--- waiting for both guns to re-cycle to BreechOpen ---")
for gn in [A,B]:
    t0=time.time()
    while not gn.rev_steady() and time.time()-t0<60: time.sleep(0.5)
    print("[%s] final: reloadState=%d steady=%s chambered=%s canfire=%s occ=%s" %
          (gn.name, g.ru32(gn.rc+0x48), gn.rev_steady(), gn.chambered(), gn.canfire(), gn.occ_list()))
