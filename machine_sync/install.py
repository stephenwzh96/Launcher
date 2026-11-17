"""Install the tool on this PC: copy it to MachineSync\\tool, name the PC, and register the "Machine sync" task
(every 5 minutes, at logon, at unlock, on wake). Replaces the trip sync's "TripSync - update desktop" (desktop) and
"TripSync - export data" (laptop) tasks."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from .gitops import NO_WINDOW
from .selfupdate import RUN_SYNC
from .settings import INTERVAL_MIN, Settings

TASK_NAME = "Machine sync"
OLD_TASKS = ("TripSync - update desktop", "TripSync - export data")
WAKE_QUERY = ("<QueryList><Query Id=\"0\" Path=\"System\"><Select Path=\"System\">*[System[Provider["
              "@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]</Select></Query></QueryList>")


def task_xml(pythonw: str, script: str, user: str, start: datetime | None = None) -> str:
    start = (start or datetime.now() + timedelta(minutes=1)).replace(microsecond=0)
    u = escape(user)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Two-way desktop/laptop sync of code (GitHub) and data (Syncthing). Status: C:\\Users\\User\\MachineSync\\sync_status.txt</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition><Interval>PT{INTERVAL_MIN}M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>{start.isoformat()}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
    <LogonTrigger><Enabled>true</Enabled><UserId>{u}</UserId><Delay>PT1M</Delay></LogonTrigger>
    <SessionStateChangeTrigger><Enabled>true</Enabled><StateChange>SessionUnlock</StateChange><UserId>{u}</UserId></SessionStateChangeTrigger>
    <EventTrigger><Enabled>true</Enabled><Subscription>{escape(WAKE_QUERY)}</Subscription><Delay>PT1M</Delay></EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{u}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(pythonw)}</Command><Arguments>-I "{escape(script)}" run</Arguments></Exec>
  </Actions>
</Task>
"""


def install(cfg: Settings, register: bool = True, pythonw: str | None = None) -> list[str]:
    done = []
    tool = cfg.sync_dir / "tool"
    source = Path(__file__).resolve().parent
    shutil.rmtree(tool, ignore_errors=True)
    shutil.copytree(source, tool / "machine_sync", ignore=shutil.ignore_patterns("__pycache__"))
    (tool / "run_sync.py").write_bytes(RUN_SYNC.encode())
    (cfg.sync_dir / "machine.txt").write_text(cfg.machine + "\n", encoding="utf-8")
    done.append(f"installed the sync tool in {tool} as {cfg.machine}")
    if not register:
        return done
    pythonw = pythonw or str(Path(sys.executable).with_name("pythonw.exe"))
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', 'User')}".lstrip("\\")
    xml_path = cfg.sync_dir / "machine_sync_task.xml"
    xml_path.write_text(task_xml(pythonw, str(tool / "run_sync.py"), user), encoding="utf-16")
    made = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
                          capture_output=True, text=True, creationflags=NO_WINDOW)
    if made.returncode != 0:
        raise RuntimeError(f"could not register the task: {made.stderr.strip() or made.stdout.strip()}")
    done.append(f'registered the "{TASK_NAME}" task (every {INTERVAL_MIN} min, logon, unlock, wake)')
    for old in OLD_TASKS:
        gone = subprocess.run(["schtasks", "/Delete", "/TN", old, "/F"], capture_output=True, text=True,
                              creationflags=NO_WINDOW)
        if gone.returncode == 0:
            done.append(f'removed the old "{old}" task')
    return done
