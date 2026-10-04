"""In-app updates: find the newest release tag on GitHub and install it.

Releases are git tags named vMAJOR.MINOR.PATCH. How the app folder got here decides how
it updates (see install_type): "git" fast-forwards the checkout, "zip-git" (a ZIP download
on a machine that has git) turns the folder into a checkout, and "zip" overlays the files
from the tag's ZIP archive. Personal files (data/, models/, config.json, .venv/) are never
touched in any mode; is_protected() is the single guard and every write path asks it.

Network, installing packages and restarting are injected so tests run without any of them.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from version import read_version

REPO_SLUG = "SirCoolMind/NoteRecall"
REPO_URL = f"https://github.com/{REPO_SLUG}"
API_BASE = f"https://api.github.com/repos/{REPO_SLUG}"
ZIP_URL = REPO_URL + "/archive/refs/tags/{tag}.zip"
ENV_REPO = "NOTERECALL_UPDATE_REPO"      # tests (and forks) point updates somewhere else

CACHE_SECONDS = 6 * 3600
RESTART_EXIT_CODE = 75                   # the launchers (and systemd) start the server again on this
MESSAGE_MAX = 400
NET_TIMEOUT = 15
GIT_TIMEOUT = 120

PROTECTED_DIRS = ("data", "models", ".venv", ".git")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
STEP_IDS = ("code", "packages", "restart")


# ---------------------------------------------------------------- pure helpers

def parse_tag(tag: str):
    """'v0.10.0' -> (0, 10, 0); None for pre-releases and anything malformed."""
    m = TAG_RE.match((tag or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def parse_version(text: str):
    return parse_tag("v" + (text or "").strip().lstrip("v"))


def latest_tag(tags):
    """Highest vMAJOR.MINOR.PATCH among tags, or None."""
    good = [t for t in tags if parse_tag(t)]
    return max(good, key=parse_tag) if good else None


def is_protected(rel: str) -> bool:
    """True for paths an update must never write: user data, models, the config file
    (holding the API key, plus its backups), the virtualenv and git's own folder."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        return False
    first = parts[0].lower()
    if first in PROTECTED_DIRS:
        return True
    return len(parts) == 1 and (first == "config.json" or first.startswith("config.json."))


def _tail(text: str, limit: int = MESSAGE_MAX) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return " | ".join(lines[-3:])[-limit:] or "no output"


def git_exe():
    return shutil.which("git")


def install_type(base_dir: Path) -> str:
    """git | zip-git | zip (see the module docstring)."""
    if not git_exe():
        return "zip"
    return "git" if (Path(base_dir) / ".git").exists() else "zip-git"


def _rmtree(path: Path):
    def onerror(func, p, _exc):  # git object files are read-only on Windows
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerror)


# ---------------------------------------------------------------- network (replaced in tests)

def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "NoteRecall-updater",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as resp:
        return resp.read()


def _http_json(url: str):
    return json.loads(_http_get(url).decode("utf-8"))


def _download(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "NoteRecall-updater"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


# ---------------------------------------------------------------- packages

def find_uv():
    uv = shutil.which("uv")
    if uv:
        return uv
    for name in ("uv.exe", "uv"):
        p = Path.home() / ".local" / "bin" / name
        if p.exists():
            return str(p)
    return None


def has_nvidia_gpu() -> bool:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        return subprocess.run([exe], capture_output=True, timeout=20,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
    except Exception:
        return False


def install_requirements(base_dir: Path, files) -> None:
    """Install the given requirements files into the interpreter running the server."""
    uv = find_uv()
    for name in files:
        path = str(Path(base_dir) / name)
        cmd = ([uv, "pip", "install", "--python", sys.executable, "-r", path] if uv
               else [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", path])
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=base_dir, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            raise RuntimeError(_tail(r.stderr or r.stdout))


def default_restart():
    """Exit with the restart code once the HTTP response has been flushed."""
    def _go():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(RESTART_EXIT_CODE)
    t = threading.Timer(1.5, _go)
    t.daemon = True
    t.start()


class StepError(Exception):
    pass


class Refused(Exception):
    """An update was refused; str(e) is the reason in plain words."""


# ---------------------------------------------------------------- the updater

class Updater:
    """base_dir: the app folder. busy: () -> bool, true while a meeting is queued or processing.
    install_packages(base_dir, files), restart() and gpu() are replaceable for tests."""

    def __init__(self, base_dir: Path, busy=lambda: False, install_packages=install_requirements,
                 restart=default_restart, gpu=has_nvidia_gpu):
        self.base_dir = Path(base_dir)
        self._busy = busy
        self._install_packages = install_packages
        self._restart = restart
        self._gpu = gpu
        self._lock = threading.Lock()
        self._cache = None            # (monotonic time, result)
        self._run = {"state": "idle", "steps": self._fresh_steps(), "target": None, "message": ""}
        self._thread = None

    # -- basics
    @staticmethod
    def _fresh_steps():
        return [{"id": i, "state": "pending", "message": ""} for i in STEP_IDS]

    @property
    def current(self) -> str:
        return read_version(self.base_dir)

    def kind(self) -> str:
        return install_type(self.base_dir)

    @staticmethod
    def _override():
        return os.environ.get(ENV_REPO) or None

    def _remote(self, kind: str) -> str:
        return "origin" if kind == "git" else (self._override() or REPO_URL)

    def _git(self, args, timeout=GIT_TIMEOUT):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        return subprocess.run([git_exe(), *args], cwd=str(self.base_dir), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _git_ok(self, args, **kw) -> str:
        r = self._git(args, **kw)
        if r.returncode != 0:
            raise StepError(_tail(r.stderr or r.stdout))
        return r.stdout

    # -- refusals
    def _refusal(self, kind=None):
        """(code, plain-words reason) when an update must not start now, else None."""
        kind = kind or self.kind()
        if self._run["state"] in ("running", "restarting"):
            return "in_progress", "An update is already in progress."
        if self._busy():
            return "busy", "NoteRecall is still working on a meeting. Wait until it finishes, then update."
        if kind == "git":
            cant = ("git_error", "Git could not check this folder for changes, so NoteRecall will not update it.")
            try:
                r = self._git(["status", "--porcelain", "--untracked-files=no"], timeout=30)
            except Exception:
                return cant
            if r.returncode != 0:
                return cant
            if r.stdout.strip():
                return "dirty", ("Some of NoteRecall's own files were changed on this computer. "
                                 "Undo those changes (or save them somewhere else) and try again.")
        return None

    def refusal(self, kind=None):
        """Plain-words reason an update must not start now, or None."""
        r = self._refusal(kind)
        return r[1] if r else None

    def version_info(self) -> dict:
        kind = self.kind()
        r = self._refusal(kind)
        return {"version": self.current, "install_type": kind, "can_update": r is None,
                "reason": r[1] if r else "", "reason_code": r[0] if r else ""}

    # -- check
    def check(self, force: bool = False) -> dict:
        current = self.current
        with self._lock:
            if not force and self._cache and time.monotonic() - self._cache[0] < CACHE_SECONDS \
                    and self._cache[1]["current"] == current:
                return dict(self._cache[1])
        result = {"current": current, "latest": None, "available": False, "notes": "",
                  "url": REPO_URL + "/releases", "checked_at": int(time.time())}
        try:
            tags = self._remote_tags()
        except Exception as e:
            result["error"] = "network"
            result["message"] = "Couldn't reach GitHub. Check your internet connection and try again."
            result["detail"] = _tail(str(e), 200)
            return result
        tag = latest_tag(tags)
        if tag:
            result["latest"] = tag[1:]
            result["tag"] = tag
            result["url"] = f"{REPO_URL}/releases/tag/{tag}"
            result["available"] = parse_tag(tag) > (parse_version(current) or (0, 0, 0))
            if result["available"]:
                result["notes"] = self._notes(tag)
        with self._lock:
            self._cache = (time.monotonic(), result)
        return dict(result)

    def _remote_tags(self):
        kind = self.kind()
        if kind == "zip":
            data = _http_json(f"{API_BASE}/tags?per_page=100")
            return [t.get("name", "") for t in data if isinstance(t, dict)]
        r = self._git(["ls-remote", "--tags", self._remote(kind)], timeout=30)
        if r.returncode != 0:
            raise RuntimeError(_tail(r.stderr or r.stdout))
        tags = []
        for line in r.stdout.splitlines():
            ref = line.split("\t")[-1].strip()
            if ref.startswith("refs/tags/"):
                tags.append(ref[len("refs/tags/"):].removesuffix("^{}"))
        return tags

    def _notes(self, tag: str) -> str:
        if self._override():       # a test or fork remote: GitHub's notes would be for another repo
            return ""
        try:
            return str(_http_json(f"{API_BASE}/releases/tags/{tag}").get("body") or "").strip()
        except Exception:
            return ""

    # -- apply
    def status(self) -> dict:
        with self._lock:
            run = self._run
            return {"state": run["state"], "running": run["state"] in ("running", "restarting"),
                    "target": run["target"], "message": run["message"],
                    "steps": [dict(s) for s in run["steps"]]}

    def apply(self) -> dict:
        """Start the update in a background thread. Raises Refused with the reason."""
        kind = self.kind()
        reason = self.refusal(kind)
        if reason:
            raise Refused(reason)
        info = self.check()
        if info.get("error"):
            raise Refused(info["message"])
        if not info["available"]:
            raise Refused("You already have the latest version.")
        with self._lock:
            if self._run["state"] in ("running", "restarting"):
                raise Refused("An update is already in progress.")
            self._run = {"state": "running", "steps": self._fresh_steps(), "target": info["latest"], "message": ""}
        self._thread = threading.Thread(target=self._do_apply, args=(kind, info["tag"]), daemon=True, name="updater")
        self._thread.start()
        return self.status()

    def _set(self, step=None, state=None, message="", overall=None):
        with self._lock:
            if step:
                for s in self._run["steps"]:
                    if s["id"] == step:
                        s["state"], s["message"] = state, message[:MESSAGE_MAX]
            if overall:
                self._run["state"] = overall
                if overall == "failed":
                    self._run["message"] = message[:MESSAGE_MAX]

    def _do_apply(self, kind: str, tag: str):
        before = self._requirements_snapshot()
        self._set("code", "running")
        try:
            if kind == "git":
                self._apply_git(tag)
            elif kind == "zip-git":
                self._apply_zip_git(tag)
            else:
                self._apply_zip(tag)
        except Exception as e:
            self._set("code", "failed", str(e) or e.__class__.__name__, overall="failed")
            return
        self._set("code", "done")
        with self._lock:
            self._cache = None

        self._set("packages", "running")
        try:
            changed = [f for f in self._requirement_files() if before.get(f) != self._read_req(f)]
            if changed:
                self._install_packages(self.base_dir, changed)
            self._set("packages", "done")
        except Exception as e:
            self._set("packages", "failed",
                      f"The new files are in place, but installing packages failed: {e}. "
                      "Close NoteRecall and start it again with start.bat (Windows) or bash start.sh (Mac/Linux) to retry.",
                      overall="failed")
            return

        self._set("restart", "running", overall="restarting")
        self._restart()

    # -- requirements bookkeeping
    def _requirement_files(self):
        return ["requirements.txt", "requirements-gpu.txt"] if self._gpu() else ["requirements.txt"]

    def _read_req(self, name: str):
        try:
            return (self.base_dir / name).read_bytes()
        except OSError:
            return None

    def _requirements_snapshot(self):
        return {f: self._read_req(f) for f in ("requirements.txt", "requirements-gpu.txt")}

    # -- getting the code
    def _guard_tree(self, tag: str):
        names = self._git_ok(["ls-tree", "-r", "--name-only", f"refs/tags/{tag}"]).splitlines()
        bad = [n for n in names if is_protected(n)]
        if bad:
            raise StepError("This release wants to change your personal files (" + bad[0] + "), so it was not installed.")

    def _apply_git(self, tag: str):
        self._git_ok(["fetch", "--tags", "--force", "origin"])
        ref = f"refs/tags/{tag}"
        self._git_ok(["rev-parse", "--verify", ref + "^{commit}"])
        self._guard_tree(tag)
        if self._git(["merge-base", "--is-ancestor", "HEAD", ref]).returncode != 0:
            raise StepError("This copy of NoteRecall has changes of its own that the new version doesn't include, "
                            "so it can't be updated automatically. Nothing was changed.")
        branch = self._git(["symbolic-ref", "-q", "--short", "HEAD"]).stdout.strip()
        if branch:
            self._git_ok(["merge", "--ff-only", ref])
        else:
            self._git_ok(["checkout", "--quiet", ref])

    def _apply_zip_git(self, tag: str):
        url = self._remote("zip-git")
        git_dir = self.base_dir / ".git"
        try:
            self._git_ok(["init", "--quiet"])
            self._git_ok(["remote", "add", "origin", url])
            self._git_ok(["fetch", "--tags", "--force", "origin"])
            self._git_ok(["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"])
            self._guard_tree(tag)
            self._git_ok(["reset", "--hard", f"refs/tags/{tag}"])
        except Exception:
            if git_dir.exists():           # leave the folder as the ZIP install it was
                _rmtree(git_dir)
            raise
        self._git_ok(["checkout", "-B", "main", f"refs/tags/{tag}"])
        if self._git(["rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"]).returncode == 0:
            self._git(["branch", "--set-upstream-to=origin/main", "main"])

    def _apply_zip(self, tag: str):
        with tempfile.TemporaryDirectory(prefix="noterecall-update-") as tmp:
            archive = Path(tmp) / "release.zip"
            _download(ZIP_URL.format(tag=tag), archive)
            self._overlay_zip(archive)

    def _overlay_zip(self, archive: Path):
        root = self.base_dir.resolve()
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            names = [m.filename for m in members]
            tops = {n.split("/", 1)[0] for n in names}
            prefix = ""
            if len(tops) == 1 and all("/" in n for n in names):
                prefix = tops.pop() + "/"      # GitHub wraps everything in NoteRecall-<version>/
            for m in members:
                rel = m.filename[len(prefix):]
                if not rel or is_protected(rel):
                    continue
                target = (self.base_dir / rel).resolve()
                if root not in target.parents:
                    raise StepError(f"unsafe path in the download: {m.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp_file = target.with_name(target.name + ".nr-new")
                try:
                    with zf.open(m) as src, open(tmp_file, "wb") as out:
                        shutil.copyfileobj(src, out)
                    os.replace(tmp_file, target)
                finally:
                    tmp_file.unlink(missing_ok=True)
