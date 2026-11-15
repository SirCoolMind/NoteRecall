"""Malay is first-class: every string exists in both dictionaries, with the same placeholders,
and every key the page asks for by name is there."""

import json
import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "static"
EN = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))
MS = json.loads((STATIC / "i18n" / "ms.json").read_text(encoding="utf-8"))
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_both_languages_have_the_same_keys():
    assert sorted(set(EN) - set(MS)) == [], "missing in ms.json"
    assert sorted(set(MS) - set(EN)) == [], "missing in en.json"


def test_no_string_is_empty_and_placeholders_match():
    for key in EN:
        assert EN[key].strip() and MS[key].strip(), key
        assert set(PLACEHOLDER.findall(EN[key])) == set(PLACEHOLDER.findall(MS[key])), key


def test_every_key_named_in_the_page_exists():
    sources = [STATIC / "index.html", *sorted((STATIC / "js").glob("*.js"))]
    # $t('key') in templates, t("key") / this.t('key') in modules; keys built at run time are skipped
    named = re.compile(r"""\bt\(\s*(['"])([a-z0-9_]+(?:\.[a-z0-9_]+)+)\1""")
    missing = sorted({m.group(2) for src in sources if "vendor" not in src.name
                      for m in named.finditer(src.read_text(encoding="utf-8"))} - set(EN))
    assert missing == []
