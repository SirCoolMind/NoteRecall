"""Pure-logic checks for the speaker ribbon, run in the browser against the real ES modules.

There is no JS unit-test runner in this project, so these import static/js/ribbon.js and
static/js/segmented.js in a Chromium page and assert on the results. Skips with the other e2e tests
when Playwright's Chromium is missing.
"""

import pytest

from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)

pytestmark = pytest.mark.e2e

CHECKS = """
async () => {
  const r = await import('/static/js/ribbon.js');
  const g = await import('/static/js/segmented.js');
  // 9 speakers; speaker n talks (n + 1) * 10 s, back to back, so ranking is 8,7,6,...,0.
  const segs = [];
  let t = 0;
  for (let n = 0; n < 9; n++) { segs.push({ speaker: n, start: t, end: t + (n + 1) * 10 }); t += (n + 1) * 10; }
  const ranking = r.rankSpeakers(segs);
  const lanes = r.buildLanes(segs, t, 1000, ranking);
  const colors = r.speakerColors(ranking);
  // 6 speakers: every one gets a lane. 7: five own lanes plus Others.
  const six = r.buildLanes(segs.filter((s) => s.speaker < 6), t, 1000);
  const seven = r.buildLanes(segs.filter((s) => s.speaker < 7), t, 1000);
  return {
    order: ranking.map((x) => x.speaker),
    shareSum: ranking.reduce((a, x) => a + x.share, 0),
    laneSpeakers: lanes.map((l) => l.speaker),
    othersCount: lanes[lanes.length - 1].others,
    othersBlocks: lanes[lanes.length - 1].blocks.length,
    sixLanes: six.length, sixHasOthers: six.some((l) => l.speaker === r.OTHERS),
    sevenLanes: seven.length, sevenOthers: seven[seven.length - 1].others,
    colorTop: colors.get(8), colorEighth: colors.get(1), colorNinth: colors.get(0),
    plausible: [
      r.isImplausibleSpeakerCount(4, 600), r.isImplausibleSpeakerCount(5, 600),
      r.isImplausibleSpeakerCount(5, 180), r.isImplausibleSpeakerCount(12, 7680),
      r.isImplausibleSpeakerCount(86, 7680), r.isImplausibleSpeakerCount(13, 36000),
      r.isImplausibleSpeakerCount(5, 95 * 60), r.isImplausibleSpeakerCount(3, 12 * 60),
    ],
    keys: ['ArrowRight', 'ArrowLeft', 'Home', 'End', 'x'].map((k) => g.nextSegment(k, 0, 9)),
    wrap: g.nextSegment('ArrowRight', 8, 9),
    share: [r.sharePercent(0.004), r.sharePercent(0.114), r.sharePercent(0)],
  };
}
"""


def test_lane_ranking_others_merge_and_plausibility(live_server, browser_page):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    out = page.evaluate(CHECKS)

    assert out["order"] == [8, 7, 6, 5, 4, 3, 2, 1, 0]            # by talk time, longest first
    assert abs(out["shareSum"] - 1) < 1e-9
    assert out["laneSpeakers"] == [8, 7, 6, 5, 4, -2]              # top 5 own lanes, then Others
    assert out["othersCount"] == 4 and out["othersBlocks"] >= 1
    assert out["sixLanes"] == 6 and not out["sixHasOthers"]        # up to 6 speakers: no merging
    assert out["sevenLanes"] == 6 and out["sevenOthers"] == 2

    assert out["colorTop"] == "var(--spk-0)"                       # colour follows talk-time rank
    assert out["colorEighth"] == "var(--spk-7)"
    assert out["colorNinth"] == "var(--ink-2)"                     # beyond the eighth: neutral

    assert out["plausible"] == [False, True, True, False, True, True, False, False]
    assert out["keys"] == [1, 8, 0, 8, -1] and out["wrap"] == 0
    assert out["share"] == ["<1%", "11%", "0%"]
