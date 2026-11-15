"""Search across every finished meeting: what was said, where, and a link to the moment."""

import json

import search

from conftest import wait_for
from test_corrections import seed

OPS = [
    {"start": 0.0, "end": 4.0, "speaker": 0, "text": "Kita kena raise change request untuk firewall rule tu."},
    {"start": 4.0, "end": 8.0, "speaker": 1, "text": "Okay, I will follow up with the vendor."},
    {"start": 754.2, "end": 760.0, "speaker": 0, "text": "Firewall rule dah approve, boleh implement Jumaat malam."},
]
BUDGET = [
    {"start": 12.5, "end": 15.0, "speaker": 2, "text": "Budget Q3 kita memang tight."},
    {"start": 15.0, "end": 19.0, "speaker": 0, "text": "The FIREWALL upgrade is not in this budget."},
]


def test_finds_a_phrase_in_every_meeting_ignoring_case(client, data_dir):
    seed(data_dir, mid="ops", segments=OPS)
    seed(data_dir, mid="budget", segments=BUDGET)
    r = client.get("/api/search", params={"q": "  Firewall   RULE "}).json()
    assert r["query"] == "firewall rule"
    assert r["total"] == 2 and list(r["meetings"]) == ["ops"]
    hits = r["meetings"]["ops"]["hits"]
    assert [(h["index"], h["start"], h["speaker"]) for h in hits] == [(0, 0.0, 0), (2, 754.2, 0)]
    assert hits[1]["text"] == OPS[2]["text"]

    both = client.get("/api/search", params={"q": "firewall"}).json()
    assert both["total"] == 3 and set(both["meetings"]) == {"ops", "budget"}


def test_each_meeting_carries_a_few_hits_and_the_full_count(client, data_dir):
    many = [{"start": float(i), "end": i + 1.0, "speaker": 0, "text": f"Server {i} dah siap."} for i in range(10)]
    seed(data_dir, mid="many", segments=many)
    found = client.get("/api/search", params={"q": "server"}).json()["meetings"]["many"]
    assert found["total"] == 10
    assert [h["index"] for h in found["hits"]] == [0, 1, 2]


def test_short_or_empty_queries_return_nothing(client, data_dir):
    seed(data_dir, mid="ops", segments=OPS)
    for q in ("", " ", "a"):
        assert client.get("/api/search", params={"q": q}).json() == {"query": q.strip(), "meetings": {}, "total": 0}
    assert client.get("/api/search").json()["total"] == 0


def test_unfinished_and_broken_meetings_are_skipped(client, data_dir):
    seed(data_dir, mid="ok", segments=OPS)
    seed(data_dir, mid="busy", segments=OPS, status="transcribing")
    seed(data_dir, mid="broken", segments=OPS)
    (data_dir / "broken" / "transcript.json").write_text("{not json", encoding="utf-8")
    (data_dir / "stray").mkdir()
    assert list(client.get("/api/search", params={"q": "firewall"}).json()["meetings"]) == ["ok"]


def test_search_follows_corrections_and_deletions(client, data_dir):
    seed(data_dir, mid="ops", segments=OPS)
    assert client.get("/api/search", params={"q": "vendor"}).json()["total"] == 1
    client.patch("/api/meetings/ops/segments/1", json={"start": 4.0, "text": "Okay, I will follow up with the supplier."})
    assert client.get("/api/search", params={"q": "vendor"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "supplier"}).json()["total"] == 1
    client.delete("/api/meetings/ops")
    assert client.get("/api/search", params={"q": "supplier"}).json()["total"] == 0
    assert "ops" not in search._cache


def test_a_new_meeting_is_searchable_once_it_is_done(client, upload):
    mid = upload("Standup")
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    found = client.get("/api/search", params={"q": "selamat pagi"}).json()
    assert found["meetings"][mid]["hits"][0]["start"] == 0.0


def test_long_lines_are_cut_around_the_match():
    text = "satu dua tiga " * 30 + "FIREWALL rule " + "empat lima enam " * 30
    at = text.casefold().find("firewall")
    cut = search.snippet(text, at, len("firewall"))
    assert "FIREWALL" in cut and cut.startswith("…") and cut.endswith("…")
    assert len(cut) <= search.SNIPPET + 2
    assert search.snippet("short line", 0, 5) == "short line"
    # a match at the very start or end is cut on one side only
    assert not search.snippet("firewall " + "x " * 200, 0, 8).startswith("…")
    tail = "x " * 200 + "firewall"
    assert search.snippet(tail, len(tail) - 8, 8).endswith("firewall")


def test_cache_is_reused_until_the_file_changes(data_dir):
    seed(data_dir, mid="ops", segments=OPS)
    search.find(data_dir, "firewall")
    first = search._cache["ops"][2]
    search.find(data_dir, "vendor")
    assert search._cache["ops"][2] is first
    (data_dir / "ops" / "transcript.json").write_text(json.dumps(BUDGET), encoding="utf-8")
    assert search.find(data_dir, "budget")["total"] == 2
