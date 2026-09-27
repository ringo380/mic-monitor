"""One-command local gate: lint, then the hardware-free tests.

    python check.py            # ruff + pytest (seconds)
    python check.py --hw       # also run the hardware tests (needs audio devices)
"""

import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
steps = [
    [sys.executable, "-m", "ruff", "check", "src", "tests", "check.py"],
    [sys.executable, "-m", "pytest", "-q"],
]
env = dict(os.environ)
if "--hw" in sys.argv:
    env["MIC_MONITOR_HW"] = "1"
    steps[1] += ["tests"]

for cmd in steps:
    print("+", " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=here, env=env).returncode
    if rc != 0:
        print(f"FAILED (exit {rc})")
        sys.exit(rc)
print("OK")
