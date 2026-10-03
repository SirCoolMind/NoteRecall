"""Review tools behind the meeting view: renamed speakers reach every export, and the overflow
actions (re-detect with a count, regenerate summary, delete) use the existing endpoints."""

import pipeline

from conftest import wait_for


def ready(client, upload, title="Standup"):
    mid = upload(title)
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    return mid


def test_renamed_speaker_reaches_every_export(client, upload):
    mid = ready(client, upload)
    client.patch(f"/api/meetings/{mid}", json={"speaker_names": {"0": "Aisyah"}})

    txt = client.get(f"/api/meetings/{mid}/export?format=txt").text
    md = client.get(f"/api/meetings/{mid}/export?format=md").text
    srt = client.get(f"/api/meetings/{mid}/export?format=srt").text
    assert "Aisyah: Selamat pagi semua." in txt
    assert "Aisyah:** Selamat pagi semua." in md
    assert "[Aisyah] Selamat pagi semua." in srt
    for body in (txt, md, srt):
        assert "Speaker 1" not in body
        assert "Speaker 2" in body  # the speaker nobody renamed keeps the default


def test_meeting_payload_carries_names_for_ribbon_and_transcript(client, upload):
    mid = ready(client, upload)
    client.patch(f"/api/meetings/{mid}", json={"speaker_names": {"1": "Ben"}})
    body = client.get(f"/api/meetings/{mid}").json()
    assert body["meta"]["speaker_names"] == {"1": "Ben"}
    assert body["summary"] == "Fake summary"


def test_rediarize_passes_the_speaker_count(client, upload, monkeypatch):
    mid = ready(client, upload)
    seen = []
    original = pipeline.rediarize_job

    def spy(audio_path, work_dir, segments, num_speakers, status_cb):
        seen.append(num_speakers)
        return original(audio_path, work_dir, segments, num_speakers, status_cb)

    monkeypatch.setattr(pipeline, "rediarize_job", spy)
    assert client.post(f"/api/meetings/{mid}/rediarize?num_speakers=3").status_code == 200
    wait_for(lambda: seen and client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    assert seen == [3]

    assert client.post(f"/api/meetings/{mid}/rediarize").status_code == 200
    wait_for(lambda: len(seen) == 2 and client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    assert seen == [3, None]  # Auto


def test_actions_requeue_the_meeting(client, fake_pipeline, upload):
    mid = ready(client, upload)
    fake_pipeline.pause()
    client.post(f"/api/meetings/{mid}/retranscribe")
    assert fake_pipeline.reached_pause.wait(timeout=10)
    assert client.get(f"/api/meetings/{mid}").json()["meta"]["status"] != "done"
    fake_pipeline.resume()
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")


def test_delete_removes_the_meeting_folder(client, data_dir, upload):
    mid = ready(client, upload)
    assert (data_dir / mid).is_dir()
    assert client.delete(f"/api/meetings/{mid}").status_code == 200
    assert not (data_dir / mid).exists()
    assert client.get(f"/api/meetings/{mid}").status_code == 404
