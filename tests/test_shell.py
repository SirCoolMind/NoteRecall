"""The app shell: / serves the new SPA shell, assets are served."""

import json
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def test_root_serves_new_shell(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'x-data="shell"' in r.text
    assert "/static/css/tokens.css" in r.text


def test_legacy_route_is_gone(client):
    assert client.get("/legacy").status_code == 404


def test_shell_assets_are_served_locally(client):
    for path in ("/static/css/tokens.css", "/static/css/app.css", "/static/js/app.js", "/static/js/home.js", "/static/js/settings.js", "/static/icons/minus.svg", "/static/icons/eye.svg", "/static/js/eta.js", "/static/js/meeting.js", "/static/js/ribbon.js", "/static/js/player.js", "/static/js/search.js", "/static/js/summary.js", "/static/icons/chevron-up.svg",
                 "/static/css/meeting.css", "/static/css/setup.css", "/static/js/setup.js",
                 "/static/vendor/alpine.min.js", "/static/fonts/barlow-400.woff2",
                 "/static/icons/upload.svg", "/static/i18n/en.json", "/static/i18n/ms.json"):
        r = client.get(path)
        assert r.status_code == 200 and r.content, path


def test_dictionaries_have_same_keys_and_status_vocabulary():
    en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))
    ms = json.loads((STATIC / "i18n" / "ms.json").read_text(encoding="utf-8"))
    assert en.keys() == ms.keys()
    assert [ms[f"status.{s}"] for s in ("queued", "processing", "ready", "failed")] == \
        ["Menunggu", "Sedang diproses", "Siap", "Gagal"]
    assert [en[f"status.{s}"] for s in ("queued", "processing", "ready", "failed")] == \
        ["Queued", "Processing", "Ready", "Failed"]
