"""Single validated build entry point for local runs and GitHub Actions."""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for args in (["-m","unittest","discover","-s","tests/multisite","-v"], ["-m","unittest","tests.test_health","-v"], ["scripts/build_multisite.py"], ["scripts/verify_multisite.py"]):
    subprocess.run([sys.executable,*args],cwd=ROOT,check=True)
print("MULTISITE_RELEASE_BUILD_PASSED")
