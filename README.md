# IRON NEST Autonomous Turret Autoloader (Ghost)

This is a Python program that plays the game IRON NEST, a heavy turret artillery simulator demo, all on its own. It reads and writes the running game's memory from an outside process, using the Windows calls `ReadProcessMemory` and `WriteProcessMemory` through `ctypes`, and it calls straight into the game's IL2CPP runtime. Once it starts, no human touches the controls. It runs a fire-control loop that drives both guns at the same time. For each shot it finds a target, works out the firing solution, stocks and cycles and rams and charges the gun, raises the barrel, and fires. The two guns share one turret and take turns in a round robin.

> This is authorized reverse engineering and modding of a single player demo, done on the author's own machine for research and learning. It changes only the local game process and nothing else.

## Demo

[![Machine Spirit in Heavy Artillery](https://img.youtube.com/vi/Gz33NfPVncA/maxresdefault.jpg)](https://www.youtube.com/watch?v=Gz33NfPVncA)

The video above shows the loader running both guns with no human help. Click the picture to watch it on YouTube.

## Architecture

- `ironnest_ghost.py` is the ghost layer. It attaches to the game process, does the memory reads and writes, runs an inline executor that calls game methods on the main thread, and resolves IL2CPP names by walking from the domain down to the assemblies, then the classes, and then the methods and fields through the `il2cpp_*` exports.
- `ironnest_probe.py` probes and maps the field offsets for `TurretController`, `GunController`, and the other game classes.
- `ironnest_parallel_rr.py` is the autoloader and the main program. It runs the pipelined two gun round robin fire-control loop.
- `draw_from_player.py` handles targeting. It reads the player's grid position, draws the map line to a target, and picks the shell type with the icon based shell picker.
- `scan_enemies.py` and `scan_artillery.py` are read only scanners that find live targets by their entity icon and health.
- `remove_line.py` clears the drawn map marker lines.
- `discharge_clean.py` is a helper that discharges any chambered round and resets both guns to a clean BreechOpen state.
- `check_both_guns.py` is a diagnostic that dumps each gun's reload state, whether it is chambered, whether it can fire, how full the cylinder is, and its elevation.
- `find_valves_full.py` maps the steam valve pressure system, which covers all the `ValveController` objects, their dials and levers, and the `HighPressureSystemManager` objects.
- `IronNest_AutoFreeze.CT`, `IronNest_Freeze.bat`, and `ironnest_freezer.py` are the Cheat Engine table and the freezer helpers.

## Reverse-engineered mechanics

These are the game internals that took real work to figure out.

- The reload state machine lives in `ArtilleryReloadController.reloadState`. It runs through numbered states from 0 to 5, where 0 is BreachLocked, 1 is BreachUnlocking, 3 is BreechOpen, and 5 is SelectPowderCharge. The breech stays locked while the barrel is raised, and it only opens after the gun comes back down to level. Ramming a round also needs the gun at level.
- The cylinder rotate lever, called `moveButton`, stays live through the whole leveling descent after a shot. The game's own `moveButton.isActive` flag guards it and switches itself off at the one unsafe instant. Because of that, the loader can turn the cylinder to the next shell while the gun is still coming down, so the rotation overlaps the leveling completely. The turn happens blind during the descent, and a trusted breech read confirms it once the breech settles.
- The steam valve pressure system has 23 `ValveController` objects, each one a PressureValve, and they gate the ram, the cylinder, the charge, the elevation, and the traverse. When a valve leaks and its `currentDamage01` climbs toward 1, the mechanism it feeds quietly stops responding. The autoloader checks every valve on each pass of the loop and reseals any leak by turning its dial, a `DialInteractable`, back to `fixedValue`.

## Optimizations in the autoloader

- The loader always uses charge 6, the maximum powder. That gives the flattest path, the lowest barrel elevation, and the least servo travel.
- The shared turret swings toward the next gun to fire as soon as that gun's card exists, so the bearing is ready early.
- Leveling sets the desired elevation back to level and lets the servo drive the barrel down smoothly, the way the real mechanism would move.
- The loader cycles the cylinder during the leveling descent, which overlaps the two steps as described above.
- The loader aims at the gun that will fire soonest, judged by how far along its reload is, so the turret keeps its swings short and avoids bouncing between the two guns.
- The loader reseals steam valves on its own, so it never stalls for lack of pressure.
- The loader picks the shell to match the target. Armored targets like tanks, bunkers, caches, and fire direction centers get AP rounds, and soft targets like infantry and field artillery get HE rounds.

## Running

```bash
# N is the number of shots, and the target mode comes from an env var
IRN_TARGET_MODE=RANDOMENEMY python ironnest_parallel_rr.py 100
```

The program reads a few environment variables. `IRN_TARGET_MODE` chooses targets and takes the value `ARTILLERY` or `RANDOMENEMY`. `IRN_ONLY_GUN` limits firing to one gun and takes `GunLeft` or `GunRight`. `IRN_VALVE_TEST=1` springs random leaks so you can watch the auto reseal handle them.

One note about paths. The scripts grew up with a `SCR` constant and some temp file paths that point at an absolute development scratch directory. To run them from a fresh checkout, set `SCR` in `ironnest_parallel_rr.py` and the temp file paths in `draw_from_player.py` to this folder.

## Validation

The loader passed two clean runs back to back, one on a fresh battlefield and one on a depleted one. Each run fired all of its shots, 100 out of 100, with zero stalls and correct HE and AP selection. Dozens of natural steam leaks resealed themselves during the runs with no pressure stall. The pace held steady at about 38 to 40 seconds per shot, since the shared turret is the one resource both guns must wait for.
