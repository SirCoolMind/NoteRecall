"""Browser checks for searching everything said: the Home search finds a phrase inside transcripts,
shows the moments on the row, and a moment opens the meeting at that second."""

import pytest

from conftest import make_wav_bytes
from test_corrections import seed
from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)
from test_e2e import expect
from test_search import BUDGET, OPS

pytestmark = pytest.mark.e2e

ROUTE_CHECKS = """
async () => {
  const r = await import('/static/js/route.js');
  const h = await import('/static/js/home.js');
  const items = [
    { id: 'a', kind: 'ready', created: '2026-09-02T10:00:00', title: 'Ops sync', quick_summary: '' },
    { id: 'b', kind: 'ready', created: '2026-09-01T10:00:00', title: 'Budget', quick_summary: 'About the firewall' },
    { id: 'c', kind: 'ready', created: '2026-08-01T10:00:00', title: 'Other', quick_summary: '' },
  ];
  const ids = (said) => h.buildSchedule(items, { query: 'firewall', said }).groups.flatMap((g) => g.items.map((m) => m.id));
  return {
    plain: r.parseRoute('#/m/20260917-173125-ab12cd'),
    moment: r.parseRoute('#/m/abc?t=754.2&q=firewall%20rule'),
    badTime: r.parseRoute('#/m/abc?t=soon'),
    home: [r.parseRoute(''), r.parseRoute('#/'), r.parseRoute('#settings/about')].map((x) => x.id),
    href: r.meetingHref('abc', { t: 754.239, q: 'firewall rule' }),
    hrefPlain: r.meetingHref('abc'),
    roundTrip: r.parseRoute(r.meetingHref('abc', { t: 12.5, q: 'a&b=c' })),
    marks: r.markQuery('The FIREWALL rule, firewall again', 'firewall'),
    noMarks: r.markQuery('nothing here', 'firewall'),
    titleOnly: ids(null),
    withSaid: ids(new Set(['c'])),
  };
}
"""


def test_route_and_schedule_logic(live_server, browser_page):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    got = page.evaluate(ROUTE_CHECKS)
    assert got["plain"] == {"id": "20260917-173125-ab12cd", "t": None, "q": ""}
    assert got["moment"] == {"id": "abc", "t": 754.2, "q": "firewall rule"}
    assert got["badTime"] == {"id": "abc", "t": None, "q": ""}
    assert got["home"] == [None, None, None]
    assert got["href"] == "#/m/abc?t=754.24&q=firewall+rule"
    assert got["hrefPlain"] == "#/m/abc"
    assert got["roundTrip"] == {"id": "abc", "t": 12.5, "q": "a&b=c"}
    assert got["marks"] == [
        {"text": "The ", "hit": False}, {"text": "FIREWALL", "hit": True}, {"text": " rule, ", "hit": False},
        {"text": "firewall", "hit": True}, {"text": " again", "hit": False}]
    assert got["noMarks"] == [{"text": "nothing here", "hit": False}]
    assert got["titleOnly"] == ["b"]            # the quick summary mentions it
    assert got["withSaid"] == ["b", "c"]        # and it was said in c


@pytest.fixture
def library(data_dir):
    for mid, segments, title in (("ops", OPS, "Ops sync"), ("budget", BUDGET, "Budget review")):
        seed(data_dir, mid=mid, segments=segments, names={"0": "Aisyah"} if mid == "ops" else None)
        meta = data_dir / mid / "meta.json"
        meta.write_text(meta.read_text(encoding="utf-8").replace('"Standup"', f'"{title}"').replace("9.0", "800.0"), encoding="utf-8")
        (data_dir / mid / "audio.wav").write_bytes(make_wav_bytes(seconds=2))
    return data_dir


def test_search_finds_what_was_said_and_opens_the_moment(live_server, browser_page, library):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    expect(page.get_by_role("link", name="Ready. Open Ops sync")).to_be_visible()

    page.get_by_role("searchbox", name="Search titles, summaries and what was said").fill("firewall rule")
    # only the meeting where it was said stays, with its two moments
    expect(page.get_by_text("Said here 2 times")).to_be_visible()
    expect(page.get_by_role("link", name="Ready. Open Budget review")).to_have_count(0)
    expect(page.get_by_text("1 of 2 · said 2 times")).to_be_visible()
    hit = page.get_by_role("link", name="Open at 12:34, Aisyah")
    expect(hit).to_contain_text("Firewall rule dah approve")
    assert hit.locator(".hit").inner_text() == "Firewall rule"

    hit.click()
    expect(page).to_have_url(live_server + "/#/m/ops?t=754.2&q=firewall+rule")
    expect(page.get_by_role("heading", name="Ops sync")).to_be_visible()
    expect(page.locator(".line.is-now")).to_contain_text("Firewall rule dah approve")
    expect(page.locator(".ribbon__clock")).to_contain_text("12:34")
    expect(page.get_by_role("searchbox", name="Search the transcript")).to_have_value("firewall rule")
    expect(page.get_by_text("2 of 2", exact=True)).to_be_visible()

    # Back on the schedule the search is still there
    page.get_by_role("link", name="Back to schedule").click()
    expect(page.get_by_text("Said here 2 times")).to_be_visible()


def test_search_moments_read_in_malay_and_clear_away(live_server, browser_page, library):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    page.get_by_role("button", name="Bahasa Melayu").click()
    box = page.get_by_role("searchbox", name="Cari tajuk, ringkasan dan apa yang disebut")
    box.fill("firewall")
    expect(page.get_by_text("Disebut di sini 2 kali")).to_be_visible()
    expect(page.get_by_text("Disebut di sini sekali")).to_be_visible()
    expect(page.get_by_role("link", name="Buka pada 0:15, Penutur 1")).to_be_visible()
    box.fill("")
    expect(page.locator(".row__said")).to_have_count(0)
    expect(page.get_by_text("2 rakaman")).to_be_visible()
