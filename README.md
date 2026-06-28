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
- `fire.bat` / `fire.ps1` is the one-click launcher. Double-click `fire.bat` and it starts the game if it is not running, loads the Chill sandbox, dismisses the intro popup, and runs the autoloader so both turrets fire on their own.
- `launch_chill.ps1` gets you into the Chill sandbox from a cold start (launch the game, load the mission, dismiss the popup) without firing. `launch_mission.py` is the lower level menu driver: it calls the game's own `MissionManager` methods through IL2CPP to press PLAY (`EnterBrowsingMap`) and start a mission (`StartOperation`) directly, so no part of the menu needs a mouse click.
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

## Requirements

- Windows. The program calls the Win32 API (`OpenProcess`, `ReadProcessMemory`, `WriteProcessMemory`, `VirtualAllocEx`) through `ctypes`, so it does not run on macOS or Linux.
- IRON NEST: Heavy Turret Simulator (Demo), installed and running. The ghost attaches by the process name `Iron Nest Heavy Turret Simulator.exe` and reads `GameAssembly.dll`. The DLL path is auto-detected from the running game's module list, so the game can be installed anywhere; the `DLL` constant in `ironnest_ghost.py`/`ironnest_probe.py`/`ironnest_freezer.py` is only a fallback used if the game isn't running yet.
- Python 3.8 or newer. There is nothing to `pip install`. Every import is from the standard library, so a plain CPython install is enough. The author ran it on Python 3.11.
- A terminal launched as Administrator. Writing another process's memory and running the inline executor need it.

## Setup

```bash
git clone https://github.com/lucastsui/iron-nest-ghost
cd iron-nest-ghost
```

No path editing is needed. Every script derives its own folder from `__file__` (so it finds `ironnest_ghost.py`, the helper scripts, and writes its temp files there), and the game's `GameAssembly.dll` is auto-detected from the running process. Clone or move the folder anywhere, install the game anywhere, and it just runs.

## Usage

### Quick start: one click to make the turrets fire

Double-click **`fire.bat`**. It launches the game if it is not already running, loads the Chill sandbox (a no-timer playground), dismisses the intro popup, and runs the autoloader so both turrets start firing on their own. The window stays open at the end so you can read the shot log.

```text
fire.bat                 # 12 shots at random enemies (default)
fire.bat 20              # 20 shots
fire.bat 30 ARTILLERY    # 30 shots, aimed at enemy artillery
```

That is all most people need. The rest of this section covers running the pieces by hand.

### Getting into a mission

You can start the game and pick a mission yourself, or let the launcher do it from a cold start:

```powershell
# launch the game (if needed) -> load the Chill sandbox -> dismiss the popup, no firing
powershell -ExecutionPolicy Bypass -File launch_chill.ps1
```

Under the hood `launch_mission.py` drives the menu through IL2CPP, with no mouse clicks: `python launch_mission.py map` presses PLAY (`EnterBrowsingMap`), and `python launch_mission.py startop Tutorial Chill` starts the Chill mission (`StartOperation`) straight from the menu.

Keep the game window in the foreground while any script runs. The game freezes its `Update()` loop when it is not the focused app, so nothing on the turret moves while you are looking at another window. Each script force-focuses the game when it starts, but do not alt-tab away while it works.

The environment-variable examples below use PowerShell. In `cmd` run `set NAME=value` on its own line first, and on a bash-like shell write `NAME=value python ...` as one line.

### Check that it attaches

A read-only state dump is the first thing to run, to confirm the ghost can see the game:

```powershell
python ironnest_ghost.py
```

Then watch the handwheels drive themselves, with no firing:

```powershell
python ironnest_ghost.py demo
```

`ironnest_ghost.py` also takes direct turret commands. `rot=20` aims to absolute bearing 20, `slew=+25` turns 25 degrees from where it is now, `elev=15` raises the barrels to 15 degrees, and `fire` fires the controlled gun once. You can combine them, for example `python ironnest_ghost.py rot=30 elev=12 fire`.

### Run the autoloader

This is the main program. It plays both guns on its own for N shots.

```powershell
# N shots, target mode from an env var
$env:IRN_TARGET_MODE="RANDOMENEMY"; python ironnest_parallel_rr.py 100
```

If you omit N it fires 4 shots. The environment variables it reads:

| Variable | Values | Effect |
| --- | --- | --- |
| `IRN_TARGET_MODE` | `ARTILLERY` (default), `RANDOMENEMY` | how it chooses targets |
| `IRN_ONLY_GUN` | `GunLeft`, `GunRight` | restrict firing to one gun, for focused tests |
| `IRN_VALVE_TEST` | `1` | spring random steam leaks so you can watch the auto-reseal handle them |

There is also a no-fire staging test that pre-stages both guns in parallel and then stops, which needs no targets on the field:

```powershell
python ironnest_parallel_rr.py STAGE
```

### Fire a single mission by hand

Given a bearing and a range read off the map, this runs one full firing cycle on one gun, covering the calculator card, the revolver load, the traverse, the elevation, and the shot:

```powershell
python ironnest_fire_mission.py <bearing> <range> [powder=3]
# e.g.
python ironnest_fire_mission.py 51.0 3.31
```

Set `IRN_SHELL` to `HE` or `AP` to choose the shell, and `IRN_GUN` to `GunLeft` or `GunRight` to choose the gun.

### Targeting and diagnostics

These help when you are debugging a run or want to see what the loader sees.

- `python scan_enemies.py` and `python scan_artillery.py` list live targets, read-only.
- `python draw_from_player.py [RANDOM|<entity name>]` reads your grid position and draws the map line to a target. With no argument it picks the nearest hostile. `IRN_PLAYER` overrides the auto-read grid code, and `IRN_EXCLUDE` is a comma-separated list of targets to skip.
- `python remove_line.py` clears any map marker lines the targeting drew.
- `python check_both_guns.py` dumps each gun's reload state, whether it is chambered, whether it can fire, how full the cylinder is, and its elevation.
- `python discharge_clean.py` discharges any chambered round and resets both guns to a clean BreechOpen state. Run it if a run leaves a gun mid-cycle.
- `python find_valves_full.py` maps the steam valve pressure system.
- `python ironnest_probe.py <Substr,Substr>` lists the IL2CPP classes whose names match and dumps the fields and methods of any class matching the substrings you pass. Use it to re-map field offsets if a game update moves them. `IRN_KW` overrides the class-name filter.

### Optional: unlimited time and requisition

For long sessions without the mission timer running out or running short on requisition points, the freezer locks the timer and sets the points high.

```powershell
python ironnest_freezer.py set=999999
```

`set=` is the requisition amount, and `secs=N` stops after N seconds (0, the default, runs until you press Ctrl+C). `IronNest_Freeze.bat` is a one-click launcher for the same thing, though you will need to edit the Python and script paths inside it to match your machine. `IronNest_AutoFreeze.CT` is a Cheat Engine table that does the equivalent if you prefer Cheat Engine.

## Validation

The loader passed two clean runs back to back, one on a fresh battlefield and one on a depleted one. Each run fired all of its shots, 100 out of 100, with zero stalls and correct HE and AP selection. Dozens of natural steam leaks resealed themselves during the runs with no pressure stall. The pace held steady at about 38 to 40 seconds per shot, since the shared turret is the one resource both guns must wait for.
