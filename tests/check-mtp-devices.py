#!/usr/bin/env python3
"""Run real Loaf UI against an isolated KMTPd service; never touch USB hardware.

Requires dbus-python, PyGObject and QtTest. The private bus disables activation
of installed services. No fake tool can forward commands to the host system.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

FAKE_DISKS = '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
if Path(sys.argv[0]).name == "lsblk":
    print('{"blockdevices": []}')
else:
    with (Path(os.environ["LOAF_DEVICE_TEST_ROOT"]) / "forbidden").open("a") as f:
        f.write(repr(sys.argv) + "\\n")
    sys.exit(1)
'''
SERVICE = r'''
import json, os
from pathlib import Path
import dbus, dbus.service, dbus.mainloop.glib
from gi.repository import GLib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
root = Path(os.environ["LOAF_DEVICE_TEST_ROOT"])
bus = dbus.SessionBus()
name = dbus.service.BusName("org.kde.kiod6", bus)
paths = ["/modules/kmtpd/phone", "/modules/kmtpd/second", "/modules/kmtpd/locked"]
present = True

class Daemon(dbus.service.Object):
    @dbus.service.method("org.kde.kmtp.Daemon", out_signature="ao")
    def listDevices(self):
        return [dbus.ObjectPath(p) for p in paths] if present else []
    @dbus.service.signal("org.kde.kmtp.Daemon")
    def devicesChanged(self): pass

class Device(dbus.service.Object):
    def __init__(self, path, key):
        super().__init__(bus, path)
        self.key, self.path = key, path
    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return {"friendlyName": "Test phone", "udi": "/test/" + self.key}
    @dbus.service.method("org.kde.kmtp.Device", out_signature="ao")
    def listStorages(self):
        return [] if self.key == "locked" else [dbus.ObjectPath(self.path + "/storage0")]

class Storage(dbus.service.Object):
    def __init__(self, key):
        super().__init__(bus, "/modules/kmtpd/" + key + "/storage0")
        self.key = key
    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return {"description": "Internal storage", "maxCapacity": dbus.UInt64(64000000000), "freeSpaceInBytes": dbus.UInt64(32000000000)}
    @dbus.service.method("org.kde.kmtp.Storage", in_signature="s", out_signature="a(uuustxs)i")
    def getFilesAndFolders(self, path):
        with (root / "list_calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"phone": self.key, "path": str(path)}) + "\n")
        if path == "/Slow": GLib.usleep(400000)
        if path not in ["/", "/Camera", "/a # % π", "/Slow", "/Empty"]:
            return [], 1
        entries = []
        if path == "/":
            if self.key == "second": entries = [("Second phone only.txt", False)]
            else: entries = [("Camera", True), ("a # % π", True), ("Slow", True), ("Empty", True), ("notes.txt", False), (".hidden", False)]
        return [dbus.Struct((dbus.UInt32(i+1), dbus.UInt32(0), dbus.UInt32(1), n, dbus.UInt64(0 if folder else 12345), dbus.Int64(1700000000), "inode/directory" if folder else "text/plain"), signature="uuustxs") for i,(n,folder) in enumerate(entries)], 0

daemon = Daemon(bus, "/modules/kmtpd")
devices = [Device(p,k) for p,k in zip(paths,["phone","second","locked"])]
storages = [Storage("phone"), Storage("second")]
def changed():
    global present
    config = json.loads((root / "config/loaf/config.json").read_text())
    next_present = config.get("mtpTestPresence") != "absent"
    if present != next_present:
        present = next_present
        daemon.devicesChanged()
    return True
GLib.timeout_add(50, changed)
print("READY", flush=True)
GLib.MainLoop().run()
'''
BUS_CONFIG = '''<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>
<auth>EXTERNAL</auth><policy context="default"><allow own="*"/>
<allow send_destination="*"/><allow receive_sender="*"/></policy></busconfig>'''


def inside(binary, directory, missing):
    sandbox = Path(directory)
    env = os.environ.copy()
    env.update(PATH=str(sandbox / "bin") + os.pathsep + env.get("PATH", os.defpath),
               XDG_CONFIG_HOME=str(sandbox / "config"), QT_QPA_PLATFORM="offscreen",
               QT_QUICK_CONTROLS_STYLE="Basic", QT_FORCE_STDERR_LOGGING="1",
               LOAF_QML=str(sandbox / "main.qml"), LOAF_DEVICE_TEST_ROOT=directory)
    service = None
    try:
        if not missing:
            service = subprocess.Popen([sys.executable, str(sandbox / "service.py")], env=env,
                                       stdout=subprocess.PIPE, text=True)
            assert service.stdout.readline().strip() == "READY", "Fixture did not start"
        def run_app(arguments, marker):
            result = subprocess.run([binary, "--new-window", *arguments], env=env, capture_output=True, text=True, timeout=45)
            output = result.stdout + result.stderr
            assert result.returncode == 0 and marker in output and "MTP_UI_TEST_FAIL" not in output and "ReferenceError:" not in output, f"App exit={result.returncode}\n{output}"
            assert not (sandbox / "forbidden").exists(), "MTP invoked a local-only tool"
            print(marker)
        run_app([], "MTP_UI_TEST_MISSING_SERVICE_PASS" if missing else "MTP_UI_TEST_ALL_PASS")
        if not missing:
            startup = "mtp://2f746573742f70686f6e65/Internal%20storage/Camera"
            config_file = sandbox / "config/loaf/config.json"
            config = json.loads(config_file.read_text())
            config["mtpStartupPath"] = startup
            config_file.write_text(json.dumps(config))
            run_app([startup], "MTP_UI_TEST_STARTUP_PASS")
    finally:
        if service:
            service.terminate()
            service.wait(timeout=5)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--inside":
        return inside(sys.argv[2], sys.argv[3], sys.argv[4] == "missing")
    root = Path(__file__).resolve().parents[1]
    binary = str(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "target/debug/loaf")
    for missing in [False, True]:
        with tempfile.TemporaryDirectory(prefix="loaf-mtp-") as directory:
            sandbox = Path(directory)
            (sandbox / "stay").mkdir()
            (sandbox / "bin").mkdir()
            for tool in ["lsblk", "udisksctl", "kioclient", "xdg-open"]:
                path = sandbox / "bin" / tool
                path.write_text(FAKE_DISKS)
                path.chmod(0o755)
            config = sandbox / "config/loaf/config.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"devicesTestRoot": directory, "mtpMissingService": str(missing).lower()}))
            (sandbox / "service.py").write_text(SERVICE)
            (sandbox / "bus.conf").write_text(BUS_CONFIG)
            source = (root / "qml/main.qml").read_text().replace("import app.loaf", "import app.loaf\nimport QtTest", 1)
            (sandbox / "main.qml").write_text(source.rsplit("}",1)[0] + (root / "tests/mtp-navigation.inc.qml").read_text() + "}\n")
            command = ["dbus-run-session", "--config-file=" + str(sandbox / "bus.conf"), "--", sys.executable, str(Path(__file__).resolve()), "--inside", binary, directory, "missing" if missing else "present"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=55)
            assert result.returncode == 0, result.stdout + result.stderr
            if not missing:
                calls = [json.loads(line) for line in (sandbox / "list_calls.jsonl").read_text().splitlines()]
                assert any(call["phone"] == "second" for call in calls), calls
                assert any(call["path"] == "/a # % π" for call in calls), calls
            print(result.stdout.strip())


if __name__ == "__main__":
    main()
