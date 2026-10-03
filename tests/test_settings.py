"""Settings: config autosave round-trip, API key masking, and the old /setup and /about redirects."""

import json

import config

KEY = "AIzaSyA-fake-test-key-1234567890abcd"


def post(client, **body):
    r = client.post("/api/config", json=body)
    assert r.status_code == 200
    return r.json()


def test_defaults_include_upload_defaults_as_auto(client):
    cfg = client.get("/api/config").json()
    assert cfg["default_language"] == ""
    assert cfg["default_speakers"] == 0
    assert cfg["engine"] == "local"


def test_every_setting_round_trips(client):
    post(client, engine="gemini", device="cpu", whisper_model="medium",
         gemini_model="gemini-2.5-pro", default_language="ms", default_speakers=3)
    cfg = client.get("/api/config").json()
    assert (cfg["engine"], cfg["device"], cfg["whisper_model"]) == ("gemini", "cpu", "medium")
    assert cfg["gemini_model"] == "gemini-2.5-pro"
    assert cfg["default_language"] == "ms"
    assert cfg["default_speakers"] == 3
    # and it really reached the file, so a restart keeps it
    on_disk = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
    assert on_disk["default_language"] == "ms" and on_disk["default_speakers"] == 3


def test_a_single_field_save_keeps_the_others(client):
    post(client, default_language="en", default_speakers=2, device="cpu")
    post(client, default_speakers=0)
    cfg = client.get("/api/config").json()
    assert cfg["default_language"] == "en" and cfg["device"] == "cpu"
    assert cfg["default_speakers"] == 0


def test_default_language_can_go_back_to_auto(client):
    post(client, default_language="en")
    assert post(client, default_language="")["default_language"] == ""


def test_speakers_accepts_numeric_strings_and_rejects_nonsense(client):
    assert post(client, default_speakers="4")["default_speakers"] == 4
    for bad in (99, -1, "abc", True, None, 2.5):
        assert post(client, default_speakers=bad)["default_speakers"] == 4
    assert post(client, default_language="fr")["default_language"] == ""


def test_invalid_engine_and_device_are_ignored(client):
    cfg = post(client, engine="skynet", device="tpu", whisper_model="huge")
    assert (cfg["engine"], cfg["device"], cfg["whisper_model"]) == ("local", "auto", "large-v3")


def test_key_is_never_returned_in_full(client):
    cfg = post(client, gemini_api_key=KEY)
    assert cfg["has_key"] is True
    assert "gemini_api_key" not in cfg
    assert KEY not in json.dumps(cfg)
    assert cfg["gemini_api_key_masked"].endswith(KEY[-4:])
    assert KEY not in client.get("/api/config").text
    # the key itself is stored, just never echoed
    assert config.load()["gemini_api_key"] == KEY


def test_no_key_reports_has_key_false(client):
    cfg = client.get("/api/config").json()
    assert cfg["has_key"] is False and cfg["gemini_api_key_masked"] == ""


def test_posting_the_masked_value_back_keeps_the_real_key(client):
    masked = post(client, gemini_api_key=KEY)["gemini_api_key_masked"]
    post(client, gemini_api_key=masked, engine="gemini")
    assert config.load()["gemini_api_key"] == KEY
    post(client, gemini_api_key="set")
    post(client, gemini_api_key="")
    post(client, gemini_api_key="   ")
    assert config.load()["gemini_api_key"] == KEY


def test_a_new_key_replaces_the_old_one(client):
    post(client, gemini_api_key=KEY)
    post(client, gemini_api_key="AIzaSyB-another-key-0987654321wxyz")
    assert config.load()["gemini_api_key"].endswith("wxyz")


def test_setup_redirects_into_the_settings_modal(client):
    r = client.get("/setup", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/#settings"


def test_about_redirects_to_the_about_section(client):
    r = client.get("/about", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/#settings/about"


def test_status_and_setup_checks_feed_the_settings_modal(client):
    status = client.get("/api/status").json()
    assert "device" in status and "engine" in status
    checks = client.get("/api/setup").json()["checks"]
    assert checks and all({"id", "name", "ok", "req"} <= set(c) for c in checks)
