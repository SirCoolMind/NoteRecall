import wave

import pytest

import ffmpeg_tools
import server


def test_env_wins(monkeypatch, tmp_path):
    exe = tmp_path / "myffmpeg.exe"
    exe.write_text("x")
    monkeypatch.setenv("FFMPEG_EXE", str(exe))
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda n: "/usr/bin/ffmpeg" if n == "ffmpeg" else None)
    assert ffmpeg_tools.resolve_ffmpeg() == (str(exe), "env")


def test_path_beats_bundled(monkeypatch):
    monkeypatch.delenv("FFMPEG_EXE", raising=False)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    assert ffmpeg_tools.resolve_ffmpeg() == ("/usr/bin/ffmpeg", "PATH")


def test_bad_env_falls_through(monkeypatch):
    monkeypatch.setenv("FFMPEG_EXE", "/nope/ffmpeg")
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda n: None)
    assert ffmpeg_tools.resolve_ffmpeg().source == "bundled"


def test_bundled_only(monkeypatch):
    monkeypatch.delenv("FFMPEG_EXE", raising=False)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda n: None)
    loc = ffmpeg_tools.resolve_ffmpeg()
    assert loc.source == "bundled" and loc.path


def test_setup_check_reports_bundled(client, monkeypatch):
    monkeypatch.delenv("FFMPEG_EXE", raising=False)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda n: None)
    checks = {c["id"]: c for c in client.get("/api/setup").json()["checks"]}
    assert checks["ffmpeg"]["ok"] and checks["ffmpeg"]["detail"].startswith("bundled")


def test_probe_duration_wav(tmp_path):
    p = tmp_path / "t.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * 3.5))
    ff = ffmpeg_tools.resolve_ffmpeg().path
    assert ffmpeg_tools.probe_duration(ff, p) == pytest.approx(3.5, abs=0.1)


def test_probe_duration_failure(tmp_path):
    p = tmp_path / "bad.wav"
    p.write_bytes(b"not audio")
    with pytest.raises(RuntimeError):
        ffmpeg_tools.probe_duration(ffmpeg_tools.resolve_ffmpeg().path, p)
