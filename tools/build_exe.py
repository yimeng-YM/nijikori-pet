"""Build the desktop EXE with all temporary output kept under tools/.build/."""
import subprocess
import sys
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    work = root / "tools" / ".build"
    work.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", "-m", "PyInstaller", "--noconfirm",
               "--distpath", str(root / "dist"), "--workpath", str(work),
               str(root / "tools" / "虹语织.spec")]
    started = time.monotonic()
    with (work / "build.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((work / "build.log").read_text(encoding="utf-8", errors="replace")[-6000:])
        return result.returncode
    print(f"EXE: {root / 'dist' / '虹语织-桌宠v2.exe'}")
    print(f"BUILD_SECONDS={time.monotonic() - started:.2f}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
