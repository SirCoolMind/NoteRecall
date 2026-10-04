"""Updater tests. No network: the "GitHub remote" is a bare git repo in a temp dir
(NOTERECALL_UPDATE_REPO), the ZIP path uses a locally built archive, and package
installs and the restart are stubbed. Nothing here touches the real checkout or data/."""

import io
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

import server
import updater
from conftest import wait_for

GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "core.autocrlf=false"]

PROTECTED = {
    "data/x.txt": b"private recording\n",
    "models/m.onnx": b"\x00weights\x01",
    "config.json": b'{"gemini_api_key": "secret"}',
    "config.json.bak": b"old secret",
}

pytestmark = pytest.mark.skipif(not updater.git_exe(), reason="git not installed")


def git(cwd, *args):
    r = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write(root: Path, rel: str, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


V1 = {
    "VERSION": "0.1.0\n", "app.txt": "one\n", "requirements.txt": "fastapi\n",
    ".gitignore": "/config.json\nconfig.json.bak\ndata/\nmodels/\n.venv/\n*.onnx\n",
}


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """A bare 'GitHub' with v0.1.0, v0.2.0 and some tags that must be ignored."""
    work, bare = tmp_path / "work", tmp_path / "remote.git"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    for rel, data in V1.items():
        write(work, rel, data)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "one")
    git(work, "tag", "-a", "v0.1.0", "-m", "0.1.0")
    write(work, "VERSION", "0.2.0\n")
    write(work, "app.txt", "two\n")
    write(work, "new_file.txt", "added in two\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "two")
    git(work, "tag", "-a", "v0.2.0", "-m", "0.2.0")
    git(work, "tag", "v1.0.0-rc1")
    git(work, "tag", "junk")
    git(work, "tag", "v0.9")
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(work, "push", "-q", str(bare), "main", "--tags")
    monkeypatch.setenv(updater.ENV_REPO, str(bare))
    return bare


class Recorder:
    def __init__(self):
        self.installed = []
        self.restarted = 0

    def install(self, base_dir, files):
        self.installed.append(list(files))

    def restart(self):
        self.restarted += 1


def make_updater(app, rec=None, busy=False):
    rec = rec or Recorder()
    u = updater.Updater(app, busy=lambda: busy, install_packages=rec.install, restart=rec.restart, gpu=lambda: False)
    return u, rec


def add_protected(app: Path):
    for rel, data in PROTECTED.items():
        write(app, rel, data)


def assert_protected_intact(app: Path):
    for rel, data in PROTECTED.items():
        assert (app / rel).read_bytes() == data, rel


def finish(u):
    u._thread.join(30)
    assert not u._thread.is_alive()
    return u.status()


@pytest.fixture
def git_app(tmp_path, remote):
    app = tmp_path / "app"
    git(tmp_path, "clone", "-q", "-b", "main", str(remote), str(app))
    git(app, "reset", "-q", "--hard", "v0.1.0")      # main is now behind v0.2.0
    add_protected(app)
    return app


# ---------------------------------------------------------------- semver

def test_semver_orders_numerically_and_ignores_prereleases_and_junk():
    assert updater.latest_tag(["v0.9.0", "v0.10.0", "v0.2.0"]) == "v0.10.0"
    assert updater.latest_tag(["v0.1.0", "v1.0.0-rc1", "junk", "v0.9", "1.2.3", "v2.0.0+build"]) == "v0.1.0"
    assert updater.latest_tag(["nope"]) is None
    assert updater.parse_tag("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("0.1.0") == (0, 1, 0)


def test_protected_paths():
    for rel in ["data/x", "data", "models/a/b.onnx", "config.json", "config.json.bak", ".venv/bin/python",
                ".git/config", "Data/x", "./data/x", "data\\x"]:
        assert updater.is_protected(rel), rel
    for rel in ["config.example.json", "static/data/x.js", "server.py", "database.py", "docs/models/x.md"]:
        assert not updater.is_protected(rel), rel


# ---------------------------------------------------------------- git install

def test_git_check_then_apply_updates_files_and_keeps_protected(git_app):
    u, rec = make_updater(git_app)
    assert u.kind() == "git"
    info = u.check()
    assert (info["current"], info["latest"], info["available"]) == ("0.1.0", "0.2.0", True)
    assert "error" not in info and info["url"].endswith("/releases/tag/v0.2.0")

    u.apply()
    st = finish(u)
    assert st["state"] == "restarting", st
    assert [s["state"] for s in st["steps"]] == ["done", "done", "running"]
    assert rec.restarted == 1
    assert (git_app / "VERSION").read_text().strip() == "0.2.0"
    assert (git_app / "app.txt").read_text().strip() == "two"
    assert (git_app / "new_file.txt").exists()
    assert_protected_intact(git_app)
    assert git(git_app, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert rec.installed == []            # requirements.txt did not change
    assert u.check(force=True)["available"] is False


def test_git_detached_head_checks_out_the_tag(git_app):
    git(git_app, "checkout", "-q", "--detach", "v0.1.0")
    u, rec = make_updater(git_app)
    u.apply()
    assert finish(u)["state"] == "restarting"
    assert git(git_app, "describe", "--tags") == "v0.2.0"
    assert_protected_intact(git_app)


def test_packages_are_installed_only_when_requirements_changed(tmp_path, remote):
    work = tmp_path / "work"
    write(work, "requirements.txt", "fastapi\nrequests\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "deps")
    git(work, "tag", "-f", "-a", "v0.2.0", "-m", "0.2.0")
    git(work, "push", "-q", "-f", str(remote), "main", "--tags")
    app = tmp_path / "app"
    git(tmp_path, "clone", "-q", "-b", "main", str(remote), str(app))
    git(app, "reset", "-q", "--hard", "v0.1.0")
    u, rec = make_updater(app)
    u.apply()
    assert finish(u)["state"] == "restarting"
    assert rec.installed == [["requirements.txt"]]


def test_package_step_failure_message(git_app, monkeypatch):
    u, rec = make_updater(git_app)
    monkeypatch.setattr(u, "_requirement_files", lambda: ["requirements.txt"])
    monkeypatch.setattr(u, "_read_req", lambda name: object())          # always "changed"
    monkeypatch.setattr(u, "_install_packages", lambda base, files: (_ for _ in ()).throw(RuntimeError("pip died")))
    u.apply()
    st = finish(u)
    assert st["state"] == "failed" and rec.restarted == 0
    assert [s["state"] for s in st["steps"]][:2] == ["done", "failed"]
    assert "pip died" in st["steps"][1]["message"] and "start.bat" in st["steps"][1]["message"]
    assert (git_app / "VERSION").read_text().strip() == "0.2.0"       # the code stays updated


def test_refuses_when_tracked_file_modified(git_app):
    (git_app / "app.txt").write_text("my edit\n")
    u, _ = make_updater(git_app)
    assert "changed on this computer" in u.refusal()
    assert u.version_info()["can_update"] is False
    with pytest.raises(updater.Refused):
        u.apply()
    assert (git_app / "app.txt").read_text() == "my edit\n"


def test_untracked_files_do_not_block(git_app):
    write(git_app, "notes.txt", "mine")
    u, _ = make_updater(git_app)
    assert u.refusal() is None


def test_refuses_while_a_meeting_is_processing(git_app):
    u, _ = make_updater(git_app, busy=True)
    assert "meeting" in u.refusal()
    with pytest.raises(updater.Refused):
        u.apply()


def test_local_commits_that_are_not_in_the_tag_fail_without_changes(git_app):
    write(git_app, "mine.txt", "local work")
    git(git_app, "add", "mine.txt")
    git(git_app, "commit", "-q", "-m", "local commit")
    u, rec = make_updater(git_app)
    u.apply()
    st = finish(u)
    assert st["state"] == "failed" and rec.restarted == 0
    assert "changes of its own" in st["steps"][0]["message"]
    assert (git_app / "VERSION").read_text().strip() == "0.1.0"


def test_already_latest_is_not_available_and_apply_refuses(git_app):
    git(git_app, "reset", "-q", "--hard", "v0.2.0")
    u, _ = make_updater(git_app)
    info = u.check()
    assert info["available"] is False and info["latest"] == "0.2.0"
    with pytest.raises(updater.Refused, match="latest"):
        u.apply()


def test_check_is_cached_for_six_hours_unless_forced(git_app, monkeypatch):
    u, _ = make_updater(git_app)
    calls = []
    real = u._remote_tags
    monkeypatch.setattr(u, "_remote_tags", lambda: calls.append(1) or real())
    u.check()
    u.check()
    assert len(calls) == 1
    u.check(force=True)
    assert len(calls) == 2


def test_unreachable_remote_is_a_friendly_state(git_app, monkeypatch):
    monkeypatch.setenv(updater.ENV_REPO, str(git_app.parent / "nowhere.git"))
    git(git_app, "remote", "set-url", "origin", str(git_app.parent / "nowhere.git"))
    u, _ = make_updater(git_app)
    info = u.check()
    assert info["error"] == "network" and "Couldn't reach GitHub" in info["message"]
    assert info["available"] is False


def test_release_that_tracks_a_protected_path_is_refused(tmp_path, git_app, remote):
    work = tmp_path / "work"
    write(work, "data/evil.txt", "x")
    git(work, "add", "-f", "data/evil.txt")
    git(work, "commit", "-q", "-m", "evil")
    git(work, "tag", "-f", "-a", "v0.3.0", "-m", "0.3.0")
    git(work, "push", "-q", str(remote), "main", "--tags")
    u, rec = make_updater(git_app)
    u.apply()
    st = finish(u)
    assert st["state"] == "failed" and "personal files" in st["steps"][0]["message"]
    assert (git_app / "VERSION").read_text().strip() == "0.1.0"
    assert not (git_app / "data" / "evil.txt").exists()
    assert_protected_intact(git_app)


# ---------------------------------------------------------------- zip download with git available

def test_zip_git_install_becomes_a_checkout(tmp_path, remote):
    app = tmp_path / "zipapp"
    for rel, data in V1.items():
        write(app, rel, data)
    write(app, "app.txt", "one (edited by the zip)\n")
    add_protected(app)
    u, rec = make_updater(app)
    assert u.kind() == "zip-git"
    u.apply()
    st = finish(u)
    assert st["state"] == "restarting", st
    assert u.kind() == "git"
    assert git(app, "describe", "--tags") == "v0.2.0"
    assert git(app, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(app, "rev-parse", "--abbrev-ref", "main@{upstream}") == "origin/main"
    assert (app / "VERSION").read_text().strip() == "0.2.0"
    assert (app / "app.txt").read_text().strip() == "two"
    assert_protected_intact(app)
    assert git(app, "ls-files", "--others", "--exclude-standard") == ""     # protected files are ignored, not untracked
    assert not [f for f in git(app, "ls-files").splitlines() if updater.is_protected(f)]


def test_zip_git_failure_leaves_no_half_made_repo(tmp_path, monkeypatch, remote):
    app = tmp_path / "zipapp"
    for rel, data in V1.items():
        write(app, rel, data)
    add_protected(app)
    u, rec = make_updater(app)
    u.check()                                              # cache the answer while the remote exists
    monkeypatch.setenv(updater.ENV_REPO, str(tmp_path / "gone.git"))
    u.apply()
    st = finish(u)
    assert st["state"] == "failed"
    assert not (app / ".git").exists()
    assert u.kind() == "zip-git"
    assert_protected_intact(app)


# ---------------------------------------------------------------- zip without git

def build_zip(path: Path, version="0.2.0"):
    with zipfile.ZipFile(path, "w") as zf:
        top = f"NoteRecall-{version}/"
        zf.writestr(top + "VERSION", version + "\n")
        zf.writestr(top + "app.txt", "two\n")
        zf.writestr(top + "static/new.js", "// new\n")
        zf.writestr(top + "data/evil.txt", "must not land")
        zf.writestr(top + "models/m.onnx", "replacement weights")
        zf.writestr(top + "config.json", "{}")
        zf.writestr(top + "config.json.bak", "{}")
        zf.writestr(top + ".venv/x", "no")
        zf.writestr(top + ".git/config", "no")


@pytest.fixture
def zip_updater(tmp_path, monkeypatch):
    monkeypatch.delenv(updater.ENV_REPO, raising=False)
    monkeypatch.setattr(updater, "git_exe", lambda: None)
    archive = tmp_path / "release.zip"
    build_zip(archive)
    seen = {}

    def fake_json(url):
        seen.setdefault("urls", []).append(url)
        if url.endswith("/tags?per_page=100"):
            return [{"name": "v0.2.0"}, {"name": "v0.1.0"}, {"name": "v1.0.0-rc1"}, {"name": "junk"}]
        return {"body": "Faster things.\nLine two <b>not html</b>"}

    def fake_download(url, dest):
        seen["zip_url"] = url
        Path(dest).write_bytes(archive.read_bytes())

    monkeypatch.setattr(updater, "_http_json", fake_json)
    monkeypatch.setattr(updater, "_download", fake_download)
    app = tmp_path / "zipnogit"
    for rel, data in V1.items():
        write(app, rel, data)
    write(app, "keep_me.txt", "local only file")
    add_protected(app)
    u, rec = make_updater(app)
    return u, rec, app, seen


def test_zip_overlay_updates_files_and_never_touches_protected_paths(zip_updater, tmp_path):
    u, rec, app, seen = zip_updater
    assert u.kind() == "zip"
    info = u.check()
    assert info["available"] and info["latest"] == "0.2.0"
    assert info["notes"] == "Faster things.\nLine two <b>not html</b>"
    u.apply()
    st = finish(u)
    assert st["state"] == "restarting", st
    assert seen["zip_url"].endswith("/archive/refs/tags/v0.2.0.zip")
    assert (app / "VERSION").read_text().strip() == "0.2.0"
    assert (app / "app.txt").read_text().strip() == "two"
    assert (app / "static" / "new.js").exists()
    assert (app / "keep_me.txt").read_text() == "local only file"      # nothing is deleted
    assert_protected_intact(app)
    assert not (app / "data" / "evil.txt").exists()
    assert not (app / ".git").exists() and not (app / ".venv").exists()
    assert not list(app.rglob("*.nr-new"))


def test_zip_with_a_path_that_escapes_the_folder_is_rejected(zip_updater, tmp_path):
    u, rec, app, seen = zip_updater
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("NoteRecall-0.2.0/VERSION", "0.2.0\n")
        zf.writestr("NoteRecall-0.2.0/../escape.txt", "no")
    with pytest.raises(updater.StepError):
        u._overlay_zip(bad)
    assert not (app.parent / "escape.txt").exists()


def test_zip_network_failure_is_friendly(zip_updater, monkeypatch):
    u, rec, app, seen = zip_updater

    def down(url):
        raise OSError("offline")
    monkeypatch.setattr(updater, "_http_json", down)
    info = u.check()
    assert info["error"] == "network" and info["available"] is False


# ---------------------------------------------------------------- API

@pytest.fixture
def api(client, git_app, monkeypatch):
    u, rec = make_updater(git_app)
    monkeypatch.setattr(server, "app_updater", u)
    return client, u, rec, git_app


def test_api_version_and_status_report_the_version(api):
    client, u, rec, app = api
    v = client.get("/api/version").json()
    assert v["version"] == (Path(server.BASE_DIR) / "VERSION").read_text().strip() == "0.1.0"
    assert v["install_type"] == "git" and v["can_update"] is True
    assert client.get("/api/status").json()["version"] == "0.1.0"


def test_api_check_and_apply_flow(api):
    client, u, rec, app = api
    c = client.get("/api/update/check").json()
    assert c["available"] and c["latest"] == "0.2.0" and c["current"] == "0.1.0"
    assert client.post("/api/update/apply").status_code == 200
    u._thread.join(30)
    st = client.get("/api/update/status").json()
    assert st["state"] == "restarting" and st["target"] == "0.2.0"
    assert [s["id"] for s in st["steps"]] == ["code", "packages", "restart"]
    # a second request while the restart is pending
    r = client.post("/api/update/apply")
    assert r.status_code == 409 and "in progress" in r.json()["detail"]


def test_api_apply_409_when_dirty(api):
    client, u, rec, app = api
    (app / "app.txt").write_text("edited")
    v = client.get("/api/version").json()
    assert v["can_update"] is False and v["reason"]
    r = client.post("/api/update/apply")
    assert r.status_code == 409 and "changed on this computer" in r.json()["detail"]


def test_api_apply_409_while_a_meeting_is_processing(api, fake_pipeline, upload):
    client, u, rec, app = api
    u._busy = server._meeting_busy
    fake_pipeline.pause()
    upload()
    wait_for(lambda: fake_pipeline.reached_pause.is_set())
    v = client.get("/api/version").json()
    assert v["can_update"] is False and "meeting" in v["reason"]
    assert client.post("/api/update/apply").status_code == 409
    fake_pipeline.resume()
    wait_for(lambda: not server._meeting_busy())
    assert client.get("/api/version").json()["can_update"] is True


def test_api_check_with_network_down_is_200(client, tmp_path, monkeypatch):
    monkeypatch.delenv(updater.ENV_REPO, raising=False)
    monkeypatch.setattr(updater, "git_exe", lambda: None)

    def down(url):
        raise OSError("offline")
    monkeypatch.setattr(updater, "_http_json", down)
    app = tmp_path / "plain"
    write(app, "VERSION", "0.1.0\n")
    monkeypatch.setattr(server, "app_updater", make_updater(app)[0])
    r = client.get("/api/update/check?force=1")
    assert r.status_code == 200 and r.json()["error"] == "network"
    assert client.post("/api/update/apply").status_code == 409
