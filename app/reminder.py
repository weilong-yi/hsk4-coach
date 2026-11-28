"""Daily study reminder: a macOS LaunchAgent that runs at the plan's time and notifies only if today's minimum is not met.

The server (re)installs it when a plan is saved, and only for the real data/study.db.

    .venv/bin/python -m app.reminder --uninstall          # turn the reminder off
    .venv/bin/python -m app.reminder --notify             # what the LaunchAgent runs at the plan's time
    .venv/bin/python -m app.reminder --notify --print --db /tmp/x.db   # print instead of notifying
"""
import argparse, json, os, plistlib, subprocess, sys, time
from pathlib import Path

from . import db, momentum

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.hsk4coach.reminder"
AGENTS = Path.home() / "Library" / "LaunchAgents"
APP_URL = "http://localhost:8766"


def plist_path(agents):
    return Path(agents) / f"{LABEL}.plist"


def plist(time_hhmm, db_path):
    hour, minute = map(int, time_hhmm.split(":"))
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "app.reminder", "--notify", "--db", str(db_path)],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
    })


def install(time_hhmm, db_path, agents=AGENTS, load=True):
    """Write the LaunchAgent for this time and (re)load it. Running it again replaces the previous one."""
    path = plist_path(agents)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(plist(time_hhmm, db_path))
    tmp.replace(path)
    if load:
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)  # fails harmlessly if not loaded
        for attempt in range(3):  # bootout can return before launchd has let go of the label
            r = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
            if r.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise OSError(f"launchctl bootstrap failed: {r.stderr.strip() or r.returncode}")
    return path


def uninstall(agents=AGENTS, load=True):
    path = plist_path(agents)
    if load:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def message(con, cfg, now):
    """The notification text, or None when there is no plan or today's minimum is already met."""
    plan = db.get_profile(con, "plan")
    if not plan or momentum.summary(momentum.load(con), cfg["momentum"], now)["today"]["met"]:
        return None
    return f"{plan['cue']}: time for Chinese ({APP_URL})"


def notify(text):
    # The text goes in as an argument, so quotes in the cue cannot break the AppleScript.
    subprocess.run(["osascript", "-e", "on run argv", "-e", 'display notification (item 1 of argv) with title "HSK 4 Coach"',
                    "-e", "end run", text], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uninstall", action="store_true", help="remove the LaunchAgent")
    ap.add_argument("--notify", action="store_true", help="notify now unless today's minimum is met")
    ap.add_argument("--print", action="store_true", help="with --notify: print the notification instead of showing it")
    ap.add_argument("--db", default=str(ROOT / "data" / "study.db"))
    args = ap.parse_args()
    if args.uninstall:
        print(f"removed {plist_path(AGENTS)}" if uninstall() else "no reminder was installed")
    elif args.notify:
        con = db.connect(args.db)
        text = message(con, json.loads((ROOT / "app" / "config.json").read_text()), db.now())
        if text is None:
            print("no reminder: no plan, or today's minimum is met")
        elif args.print:
            print(f"notify: {text}")
        else:
            notify(text)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
