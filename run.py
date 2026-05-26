import subprocess
import sys

subprocess.run(
    [sys.executable, "-m", "uvicorn", "main:app", "--reload"],
    cwd=__file__.replace("run.py", "")
)

#