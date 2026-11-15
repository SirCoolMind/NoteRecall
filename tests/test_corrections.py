"""Correcting a finished transcript: edit a line, move a line or a turn to another speaker, delete a
line, merge speakers, and put everything back. The untouched transcript is kept beside the corrected
one, and every export follows the corrections."""

import json

import pytest

import corrections

from conftest import CANNED_SEGMENTS, wait_for

FOUR = [
    {"start": 0.0, "end": 2.0, "speaker": 0, "text": "Selamat pagi semua."},
    {"start": 2.0, "end": 4.0, "speaker": 0, "text": "Kita mula ya."},
    {"start": 4.0, "end": 6.0, "speaker": 1, "text": "Good morning."},
    {"start": 6.0, "end": 9.0, "speaker": 2, "text": "Morning, sorry lambat."},
]


def seed(data_dir, mid="m1", segments=FOUR, names=None, engine="extractive", status="done"):
    d = data_dir / mid
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "id": mid, "title": "Standup", "created": "2026-09-17T17:31:00", "audio_file": "audio.wav",
        "status": status, "progress": 100, "duration": 9.0, "speaker_names": names or {},
        "num_speakers_found": 3, "summary_engine": engine}), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    (d / "summary.md").write_text("Old summary", encoding="utf-8")
    return mid


def segs(client, mid):
    return client.get(f"/api/meetings/{mid}").json()["segments"]


def test_edit_a_line_keeps_the_original_and_reaches_exports(client, data_dir):
    mid = seed(data_dir)
    r = client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "text": "  Good   morning, everyone. "})
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] == {"2": {"start": 4.0, "end": 6.0, "speaker": 1,
                                     "text": "Good morning, everyone.", "orig": "Good morning."}}
    assert body["corrected"] is True

    assert segs(client, mid)[2]["text"] == "Good morning, everyone."
    for fmt in ("txt", "md", "srt"):
        assert "Good morning, everyone." in client.get(f"/api/meetings/{mid}/export?format={fmt}").text
    # the untouched transcript sits beside the corrected one
    kept = json.loads((data_dir / mid / corrections.ORIGINAL_FILE).read_text(encoding="utf-8"))
    assert kept["segments"] == FOUR


def test_a_second_edit_still_remembers_the_first_original(client, data_dir):
    mid = seed(data_dir)
    client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "text": "Good morning all."})
    client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "text": "Good morning, team."})
    assert segs(client, mid)[2]["orig"] == "Good morning."
    # typing the original back clears the mark
    client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "text": "Good morning."})
    assert "orig" not in segs(client, mid)[2]


def test_restore_one_line(client, data_dir):
    mid = seed(data_dir)
    client.patch(f"/api/meetings/{mid}/segments/0", json={"start": 0.0, "text": "Selamat petang semua."})
    r = client.patch(f"/api/meetings/{mid}/segments/0", json={"start": 0.0, "restore": True})
    assert r.json()["changed"]["0"] == FOUR[0]


def test_bad_edits_are_refused_and_change_nothing(client, data_dir):
    mid = seed(data_dir)
    assert client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "text": "   "}).status_code == 400
    assert client.patch(f"/api/meetings/{mid}/segments/9", json={"start": 4.0, "text": "x"}).status_code == 400
    # the page thinks line 2 starts somewhere else: the transcript changed under it
    assert client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 5.5, "text": "x"}).status_code == 400
    assert client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "speaker": 7}).status_code == 400
    assert segs(client, mid) == FOUR
    assert not (data_dir / mid / corrections.ORIGINAL_FILE).exists()
    assert client.get(f"/api/meetings/{mid}").json()["corrected"] is False


def test_move_one_line_or_the_whole_turn_to_another_speaker(client, data_dir):
    mid = seed(data_dir)
    r = client.patch(f"/api/meetings/{mid}/segments/1", json={"start": 2.0, "speaker": 1})
    assert list(r.json()["changed"]) == ["1"]
    assert [s["speaker"] for s in segs(client, mid)] == [0, 1, 1, 2]

    # lines 1 and 2 are now one turn; move the turn
    r = client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "speaker": 2, "turn": True})
    assert sorted(r.json()["changed"]) == ["1", "2"]
    assert [s["speaker"] for s in segs(client, mid)] == [0, 2, 2, 2]
    assert r.json()["meta"]["num_speakers_found"] == 2


def test_a_new_speaker_gets_the_next_number(client, data_dir):
    mid = seed(data_dir)
    r = client.patch(f"/api/meetings/{mid}/segments/3", json={"start": 6.0, "speaker": "new"})
    assert r.json()["changed"]["3"]["speaker"] == 3
    assert r.json()["meta"]["num_speakers_found"] == 3   # speaker 2 has no lines left


def test_delete_a_line(client, data_dir):
    mid = seed(data_dir)
    r = client.delete(f"/api/meetings/{mid}/segments/1?start=2.0")
    assert r.status_code == 200 and r.json()["removed"] == 1
    assert [s["text"] for s in segs(client, mid)] == [FOUR[0]["text"], FOUR[2]["text"], FOUR[3]["text"]]
    assert client.delete(f"/api/meetings/{mid}/segments/1?start=2.0").status_code == 400   # stale


def test_merge_speakers_moves_the_name_and_the_lines(client, data_dir):
    mid = seed(data_dir, names={"2": "Aisyah"})
    r = client.post(f"/api/meetings/{mid}/speakers/merge", json={"from": 2, "into": 0})
    assert r.status_code == 200
    assert [s["speaker"] for s in segs(client, mid)] == [0, 0, 1, 0]
    meta = r.json()["meta"]
    assert meta["speaker_names"] == {"0": "Aisyah"}      # the target had no name, so it takes this one
    assert meta["num_speakers_found"] == 2
    assert "Aisyah: Morning, sorry lambat." in client.get(f"/api/meetings/{mid}/export").text

    assert client.post(f"/api/meetings/{mid}/speakers/merge", json={"from": 0, "into": 0}).status_code == 400
    assert client.post(f"/api/meetings/{mid}/speakers/merge", json={"from": 2, "into": 0}).status_code == 400


def test_merge_keeps_the_targets_own_name(client, data_dir):
    mid = seed(data_dir, names={"0": "Ben", "2": "Aisyah"})
    meta = client.post(f"/api/meetings/{mid}/speakers/merge", json={"from": 2, "into": 0}).json()["meta"]
    assert meta["speaker_names"] == {"0": "Ben"}


def test_discard_puts_everything_back(client, data_dir):
    mid = seed(data_dir, names={"0": "Aisyah"})
    client.patch(f"/api/meetings/{mid}/segments/2", json={"start": 4.0, "text": "Changed."})
    client.delete(f"/api/meetings/{mid}/segments/3?start=6.0")
    client.post(f"/api/meetings/{mid}/speakers/merge", json={"from": 1, "into": 0})
    client.patch(f"/api/meetings/{mid}", json={"speaker_names": {"0": "Someone else"}})

    r = client.post(f"/api/meetings/{mid}/corrections/discard")
    assert r.status_code == 200
    body = r.json()
    assert body["segments"] == FOUR
    assert body["corrected"] is False
    assert body["meta"]["speaker_names"] == {"0": "Aisyah"}
    assert body["meta"]["num_speakers_found"] == 3
    assert not (data_dir / mid / corrections.ORIGINAL_FILE).exists()
    assert client.post(f"/api/meetings/{mid}/corrections/discard").status_code == 400


def test_builtin_summary_follows_corrections_at_once(client, data_dir):
    mid = seed(data_dir, engine="extractive")
    body = client.post(f"/api/meetings/{mid}/speakers/merge", json={"from": 2, "into": 0}).json()
    assert "Speaker 3" not in body["summary"] and "Speaker 1" in body["summary"]
    assert "summary_stale" not in body["meta"]
    # renaming a speaker rewrites it too, so the .md export carries the name
    client.patch(f"/api/meetings/{mid}", json={"speaker_names": {"0": "Aisyah"}})
    assert "**Aisyah**" in client.get(f"/api/meetings/{mid}/export?format=md").text


def test_ai_summary_is_kept_and_marked_stale(client, data_dir):
    mid = seed(data_dir, engine="ollama:qwen2.5:7b")
    body = client.patch(f"/api/meetings/{mid}/segments/0", json={"start": 0.0, "text": "Selamat petang."}).json()
    assert body["summary"] == "Old summary"
    assert body["meta"]["summary_stale"] is True
    # a rename alone does not make an AI summary stale
    mid2 = seed(data_dir, mid="m2", engine="ollama:qwen2.5:7b")
    assert "summary_stale" not in client.patch(f"/api/meetings/{mid2}", json={"speaker_names": {"0": "A"}}).json()
    # writing the summary again clears the mark
    client.post(f"/api/meetings/{mid}/resummarize")
    assert "summary_stale" not in client.get(f"/api/meetings/{mid}").json()["meta"]


def test_no_corrections_while_processing(client, fake_pipeline, upload):
    fake_pipeline.pause()
    mid = upload("Busy")
    assert fake_pipeline.reached_pause.wait(timeout=10)
    assert client.patch(f"/api/meetings/{mid}/segments/0", json={"start": 0.0, "text": "x"}).status_code == 409
    assert client.post(f"/api/meetings/{mid}/speakers/merge", json={"from": 0, "into": 1}).status_code == 409
    assert client.post(f"/api/meetings/{mid}/corrections/discard").status_code == 409
    fake_pipeline.resume()
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")


def test_retranscribe_makes_a_new_original(client, upload):
    mid = upload("Standup")
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    client.patch(f"/api/meetings/{mid}/segments/0", json={"start": 0.0, "text": "Corrected."})
    assert client.get(f"/api/meetings/{mid}").json()["corrected"] is True

    client.post(f"/api/meetings/{mid}/retranscribe")
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done"
             and client.get(f"/api/meetings/{mid}").json()["corrected"] is False)
    body = client.get(f"/api/meetings/{mid}").json()
    assert body["segments"] == CANNED_SEGMENTS


def test_text_corrections_survive_a_speaker_redetect(client, upload):
    mid = upload("Standup")
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    client.patch(f"/api/meetings/{mid}/segments/0", json={"start": 0.0, "text": "Selamat petang semua."})
    client.post(f"/api/meetings/{mid}/rediarize?num_speakers=2")
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["corrected"] is False)
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    first = client.get(f"/api/meetings/{mid}").json()["segments"][0]
    assert first["text"] == "Selamat petang semua." and first["orig"] == "Selamat pagi semua."


def test_known_names_come_from_every_meeting(client, data_dir):
    seed(data_dir, mid="a", names={"0": "Aisyah", "1": "ben"})
    seed(data_dir, mid="b", names={"0": "Aisyah", "3": "Daniel"})
    assert client.get("/api/meetings/a").json()["known_names"] == ["Aisyah", "ben", "Daniel"]


def test_turn_range_and_new_ids_are_pure():
    s = [{"speaker": 1}, {"speaker": 1}, {"speaker": 0}, {"speaker": 1}]
    assert list(corrections.turn_range(s, 1)) == [0, 1]
    assert list(corrections.turn_range(s, 3)) == [3]
    assert corrections.new_speaker_id(s) == 2
    assert corrections.new_speaker_id([{"speaker": -1}]) == 0
    with pytest.raises(corrections.CorrectionError):
        corrections.clean_text("x" * (corrections.MAX_TEXT + 1))
