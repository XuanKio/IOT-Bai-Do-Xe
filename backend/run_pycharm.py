"""Run from PyCharm: start the local broker, then serve the API and dashboard."""
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUNTIME = ROOT / "mqtt" / "runtime"
HOST, PORT = "127.0.0.1", 8000


def check_runtime():
    required = [RUNTIME / "backend.env", RUNTIME / "connection.json",
                RUNTIME / "mosquitto.conf", ROOT / ".tools" / "mosquitto" / "mosquitto.exe"]
    if os.name != "nt":
        raise RuntimeError("This launcher uses the project's Windows MQTT scripts.")
    if any(not path.is_file() for path in required):
        raise RuntimeError("Local configuration is missing. Run mqtt/Setup.ps1 from the project root first.")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, PORT))
        except OSError as error:
            raise RuntimeError(
                "Port 8000 is unavailable. Stop the other Run session or run mqtt/Stop-IOT.ps1, then retry."
            ) from error


def main():
    print("Starting IoT Dashboard...", flush=True)
    try:
        from dotenv import load_dotenv
        import uvicorn
    except ImportError:
        print("Missing dependencies. Select backend/.venv/Scripts/python.exe as the Python interpreter.", file=sys.stderr)
        return 1
    try:
        print("Checking local configuration and port 8000...", flush=True)
        check_runtime()
        print("Starting/reusing the MQTT broker...", flush=True)
        # A background broker can inherit PowerShell's handles. Use a file rather
        # than capture_output pipes, whose EOF would wait for that broker to exit.
        with (RUNTIME / "pycharm-broker-start.log").open("w+", encoding="utf-8") as log:
            broker = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                 str(ROOT / "mqtt" / "Start-IOT.ps1"), "-BrokerOnly"],
                cwd=ROOT, timeout=45, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log.seek(0)
            output = log.read()
        if output.strip():
            print(output.strip(), flush=True)
        if broker.returncode:
            raise RuntimeError("MQTT broker startup failed. Check mqtt/runtime/broker.stdout.log and broker.stderr.log.")
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    os.chdir(BACKEND)
    load_dotenv(RUNTIME / "backend.env", override=False)
    print(f"Python: {sys.executable}", flush=True)
    print(f"Dashboard: http://{HOST}:{PORT}/", flush=True)
    print(f"API docs: http://{HOST}:{PORT}/docs", flush=True)
    print("Login details: mqtt/runtime/THONG_TIN_DANG_NHAP.txt", flush=True)
    print("Stop this Run session to stop the backend; mqtt/Stop-IOT.ps1 also stops the broker.", flush=True)
    # Keep a single process so PyCharm Run/Debug and breakpoints work normally.
    uvicorn.run("app.main:app", host=HOST, port=PORT, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
