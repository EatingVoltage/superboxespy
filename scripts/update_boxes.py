"""Update the vendored boxes.py (python/boxes) to a newer upstream commit, then run the tests.

    python scripts/update_boxes.py [commit-or-branch]      (default: master)

Clones https://github.com/florianfesti/boxes into a temp folder, swaps python/boxes for its boxes/ package and
records the commit in python/boxes/UPSTREAM_COMMIT. Saved boxes remember the commit they were made with, and the app
warns when it differs - check those boxes' parts before cutting them again.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "python", "boxes")
REPO = "https://github.com/florianfesti/boxes.git"


def run(*cmd, cwd=None):
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "master"
    tmp = tempfile.mkdtemp(prefix="boxes-upstream-")
    try:
        run("git", "clone", "--quiet", "--filter=blob:none", REPO, tmp)
        run("git", "checkout", "--quiet", ref, cwd=tmp)
        info = subprocess.run(["git", "log", "-1", "--format=%h %H %ci"], cwd=tmp, check=True,
                              capture_output=True, text=True).stdout.split(maxsplit=1)
        old = open(os.path.join(TARGET, "UPSTREAM_COMMIT"), encoding="utf-8").read().split()[0]
        backup = TARGET + ".old"
        shutil.rmtree(backup, ignore_errors=True)
        os.rename(TARGET, backup)
        shutil.copytree(os.path.join(tmp, "boxes"), TARGET, ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(TARGET, "UPSTREAM_COMMIT"), "w", encoding="utf-8", newline="\n") as f:
            f.write("%s\n%s" % (info[0], info[1]))
        print("boxes.py %s -> %s" % (old, info[0]))
        tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT)
        if tests.returncode:
            print("Tests FAILED with the new boxes.py. The old one is in python/boxes.old - "
                  "to go back: delete python/boxes and rename python/boxes.old to python/boxes.")
            sys.exit(1)
        shutil.rmtree(backup, ignore_errors=True)
        print("Tests pass. Rebuild the app: npm run build")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
