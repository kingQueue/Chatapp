"""Run one Soup command in WSL and relay cancellation from Character Room."""
from contextlib import suppress
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


CANCEL = ".soup-cancel"


def run(args):
    cancelled = Path(CANCEL)
    if cancelled.exists():
        return 130
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", NO_COLOR="1")
    with subprocess.Popen(args, stdin=subprocess.DEVNULL, env=env, start_new_session=True) as process:
        while process.poll() is None:
            if cancelled.exists():
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                return 130
            time.sleep(0.25)
        return process.returncode


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
