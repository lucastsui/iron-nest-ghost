# IRON NEST — Autonomous Turret Autoloader ("Ghost")

A Python tool that autonomously plays **IRON NEST: Heavy Turret Simulator (Demo)** by reading and
writing the game's memory from an external process (`ctypes` `ReadProcessMemory`/`WriteProcessMemory`)
and invoking its **IL2CPP runtime** directly. It runs a fully hands-off, dual-gun artillery
fire-control loop: acquire target → compute firing solution → stock/cycle/ram/charge → elevate →
fire, both guns pipelined in a round-robin.

> Authorized reverse-engineering / modding of a **single-player demo** on the author's own machine,
> for research and educational purposes. It manipulates only the local game process.

---

## Architecture

| File | Role |
|------|------|
| `ironnest_ghost.py` | The **ghost**: process attach, RPM/WPM, an inline main-thread call executor, and IL2CPP resolution (domain → assemblies → classes → methods/fields via `il2cpp_*` exports). |
| `ironnest_probe.py` | Field-offset probe / map for `TurretController`, `GunController`, etc. |
| `ironnest_parallel_rr.py` | **The autoloader.** The pipelined dual-gun round-robin fire-control loop (the main program). |
| `draw_from_player.py` | Targeting: reads the player grid position, draws the map line to a target, and picks the shell type (the icon-based shell picker). |
| `scan_enemies.py` / `scan_artillery.py` | Read-only live-target scanners (by entity icon / health). |
| `remove_line.py` | Clears drawn map-marker lines. |
| `discharge_clean.py` | Utility: discharges any chambered round and resets both guns to a clean BreechOpen state. |
| `check_both_guns.py` | Diagnostic: dumps each gun's reload state / chambered / CanFire / cylinder occupancy / elevation. |
| `find_valves_full.py` | Maps the steam-valve pressure system (all `ValveController`s, their dials/levers, and `HighPressureSystemManager`s). |
| `IronNest_AutoFreeze.CT`, `IronNest_Freeze.bat`, `ironnest_freezer.py` | Cheat Engine table + freezer helpers. |

## Hard-won reverse-engineered mechanics

- **Reload state machine** — `ArtilleryReloadController.reloadState` (0 BreachLocked → 1 BreachUnlocking → 2 → 3 BreechOpen → 5 SelectPowderCharge). The breech is **locked** while the barrel is elevated and only opens after the gun returns to level; ramming requires level.
- **Mid-leveling cylinder cycle** — the cylinder rotate-lever (`moveButton`) is *live during the whole post-fire leveling descent*, gated by the game's own `moveButton.isActive` flag (which self-disables at the one unsafe instant). So the cylinder can be cycled to the next shell *while the gun is still lowering*, fully overlapping leveling. Rotation is done blind during the descent, then verified by an authoritative breech read once the breech settles.
- **Steam-valve pressure system** — 23 `ValveController`s ("PressureValve") gate the ram / cylinder / charge / elevation / traverse mechanisms. When valves leak (`currentDamage01` → 1) the affected mechanism silently stops responding. The autoloader scans all valves each loop and reseals any leak by turning its dial (`DialInteractable`) back to `fixedValue`.

## Optimizations in the autoloader

- **Charge-6 ballistics** — always max powder → flattest trajectory → lowest elevation → least servo travel.
- **Early bearing** — the shared turret slews to the next-to-fire gun as soon as its card exists.
- **Servo leveling** — sets *desired* elevation to level (immersive, not a snap).
- **Mid-leveling cylinder overlap** — cycle the cylinder during the leveling descent (see above).
- **Rank-based aim** — aim at the gun that will fire *soonest* (by load progress), not nearest bearing, to avoid wasted turret "ping-pong".
- **Steam-valve auto-reseal** — never pressure-stalls.
- **Shell selection** — armored targets (tanks, bunkers/caches, **FDCs**) → AP; soft (infantry, field artillery) → HE.

## Running

```bash
# N = number of shots; target mode via env var
IRN_TARGET_MODE=RANDOMENEMY python ironnest_parallel_rr.py 100
```

Useful env vars: `IRN_TARGET_MODE` (`ARTILLERY` | `RANDOMENEMY`), `IRN_ONLY_GUN` (`GunLeft`/`GunRight`),
`IRN_VALVE_TEST=1` (spring random leaks to exercise the auto-reseal).

> **Paths:** the scripts were developed with a `SCR` constant and some temp-file paths pointing at an
> absolute development scratchpad directory. To run from a clean checkout, point `SCR` (in
> `ironnest_parallel_rr.py`) and the temp-file paths (in `draw_from_player.py`) at this folder.

## Validation

Validated with two consecutive clean **100-shot** runs (fresh and depleted battlefields): 100/100 shots,
**zero stalls**, correct HE/AP selection, and dozens of natural steam leaks auto-resealed with no
pressure-stall — at a steady ~38–40 s/shot wall-clock (the shared turret is the serial resource).
