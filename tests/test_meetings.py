import json

from conftest import CANNED_SEGMENTS, wait_for


def meta_of(client, mid):
    return client.get(f"/api/meetings/{mid}").json()["meta"]


def test_upload_goes_queued_processing_done(client, fake_pipeline, upload):
    fake_pipeline.pause()
    first = upload("First")
    # park the worker on the first job so the second stays queued
    assert fake_pipeline.reached_pause.wait(timeout=10)
    second = upload("Second")

    assert meta_of(client, first)["status"] == "transcribing"
    assert 0 < meta_of(client, first)["progress"] < 100
    assert meta_of(client, second)["status"] == "queued"

    fake_pipeline.resume()
    for mid in (first, second):
        wait_for(lambda: meta_of(client, mid)["status"] == "done")
    body = client.get(f"/api/meetings/{first}").json()
    assert body["meta"]["progress"] == 100
    assert body["segments"] == CANNED_SEGMENTS
    assert body["summary"] == "Fake summary"


def test_patch_title(client, upload):
    mid = upload("Old name")
    wait_for(lambda: meta_of(client, mid)["status"] == "done")

    r = client.patch(f"/api/meetings/{mid}", json={"title": "  New name  "})
    assert r.status_code == 200
    assert meta_of(client, mid)["title"] == "New name"

    # a blank title is ignored
    client.patch(f"/api/meetings/{mid}", json={"title": "   "})
    assert meta_of(client, mid)["title"] == "New name"


def test_patch_speaker_names(client, upload):
    mid = upload("Standup")
    wait_for(lambda: meta_of(client, mid)["status"] == "done")

    client.patch(f"/api/meetings/{mid}", json={"speaker_names": {"0": "Aisyah"}})
    client.patch(f"/api/meetings/{mid}", json={"speaker_names": {"1": "Ben", "2": " "}})
    assert meta_of(client, mid)["speaker_names"] == {"0": "Aisyah", "1": "Ben"}
    assert "Aisyah" in client.get(f"/api/meetings/{mid}/export").text


def test_title_edit_during_processing_survives(client, fake_pipeline, upload):
    """Regression: the worker's progress writes used to revert a mid-job rename."""
    fake_pipeline.pause()
    mid = upload("Original")
    assert fake_pipeline.reached_pause.wait(timeout=10)

    client.patch(f"/api/meetings/{mid}",
                 json={"title": "Renamed mid-job", "speaker_names": {"0": "Aisyah"}})
    fake_pipeline.resume()
    wait_for(lambda: meta_of(client, mid)["status"] == "done")

    meta = meta_of(client, mid)
    assert meta["title"] == "Renamed mid-job"
    assert meta["speaker_names"] == {"0": "Aisyah"}


def test_title_edit_while_queued_survives(client, fake_pipeline, upload):
    fake_pipeline.pause()
    first = upload("First")
    assert fake_pipeline.reached_pause.wait(timeout=10)
    second = upload("Second")  # stays queued behind the first

    client.patch(f"/api/meetings/{second}", json={"title": "Second, renamed"})
    fake_pipeline.resume()
    wait_for(lambda: meta_of(client, second)["status"] == "done")
    assert meta_of(client, second)["title"] == "Second, renamed"
    assert meta_of(client, first)["title"] == "First"


def test_rediarize_resets_speaker_names_but_keeps_title(client, fake_pipeline, upload):
    mid = upload("Keep me")
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    client.patch(f"/api/meetings/{mid}", json={"speaker_names": {"0": "Aisyah"}})

    fake_pipeline.pause()
    assert client.post(f"/api/meetings/{mid}/rediarize").status_code == 200
    assert fake_pipeline.reached_pause.wait(timeout=10)
    client.patch(f"/api/meetings/{mid}", json={"title": "Renamed during rediarize"})
    fake_pipeline.resume()
    wait_for(lambda: meta_of(client, mid)["status"] == "done")

    meta = meta_of(client, mid)
    assert meta["speaker_names"] == {}
    assert meta["title"] == "Renamed during rediarize"


def _seed(data_dir, mid, title, summary=None, created="2026-09-17T17:31:00"):
    d = data_dir / mid
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "id": mid, "title": title, "created": created, "audio_file": "audio.wav",
        "status": "done", "progress": 100, "duration": 3727.0, "speaker_names": {}}), encoding="utf-8")
    if summary is not None:
        (d / "summary.md").write_text(summary, encoding="utf-8")


def test_list_has_quick_summary_from_the_overview(client, data_dir):
    _seed(data_dir, "a1", "With overview",
          "## Ringkasan / Overview\nThe team **agreed** on the [launch plan](http://x.test)\nand the budget.\n\n"
          "## Perkara Utama / Key Points\n- Point one\n- Point two\n")
    _seed(data_dir, "a2", "Key points only",
          "## Perkara Utama / Key Points\n- First *point*\n- Second point\n\n> _Ringkasan automatik (extractive)._\n")
    _seed(data_dir, "a3", "No summary")
    _seed(data_dir, "a4", "Long", "## Overview\n" + "word " * 200)
    by_id = {m["id"]: m for m in client.get("/api/meetings").json()}

    assert by_id["a1"]["quick_summary"] == "The team agreed on the launch plan and the budget."
    assert by_id["a2"]["quick_summary"] == "First point; Second point"
    assert by_id["a3"]["quick_summary"] == ""
    assert len(by_id["a4"]["quick_summary"]) <= 280 and by_id["a4"]["quick_summary"].endswith("…")


def test_malformed_summary_does_not_break_the_list(client, data_dir):
    _seed(data_dir, "b1", "Bad bytes")
    (data_dir / "b1" / "summary.md").write_bytes(b"\xff\xfe\x00 not utf-8 \xff")
    _seed(data_dir, "b2", "Fine", "## Overview\nAll good.")
    by_id = {m["id"]: m for m in client.get("/api/meetings").json()}
    assert by_id["b1"]["quick_summary"] == ""
    assert by_id["b2"]["quick_summary"] == "All good."
