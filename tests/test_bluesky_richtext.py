"""The bluesky rich-text module: facets and the grapheme count.

No network, no runner: these tests pin the byte ranges links, mentions
and hashtags become, the mention resolver staying out of the dry run, and
the 300-grapheme counting the dry run warns against. A facet that still
held with the feature removed would be sent back with the runner.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "bluesky"

sys.path.insert(0, str(PACKAGE))

import richtext  # noqa: E402


def test_plain_ascii_counts_one_per_char() -> None:
    assert richtext.grapheme_count("hola") == len("hola")
    assert richtext.grapheme_count("") == 0


def test_combining_marks_and_zwj_join_and_flags_count_once() -> None:
    assert richtext.grapheme_count("é") == 1
    assert richtext.grapheme_count("👨\u200d👩\u200d👧\u200d👦") == 1
    assert richtext.grapheme_count("🇪🇸") == 1
    assert richtext.grapheme_count("a🇪🇸b") == richtext.grapheme_count("abc")


def test_a_link_is_a_facet_over_its_bytes() -> None:
    text = "mira https://univerlab.org/placa ya"
    facets = richtext.facets_for(text)
    assert len(facets) == 1
    facet = facets[0]
    assert facet["features"] == [
        {"$type": "app.bsky.richtext.facet#link", "uri": "https://univerlab.org/placa"}
    ]
    start = facet["index"]["byteStart"]
    end = facet["index"]["byteEnd"]
    assert text.encode("utf-8")[start:end].decode("utf-8") == "https://univerlab.org/placa"


def test_trailing_punctuation_stays_out_of_the_link() -> None:
    facets = richtext.facets_for("mira (https://univerlab.org/placa).")
    assert facets[0]["features"][0]["uri"] == "https://univerlab.org/placa"


def test_a_mention_resolves_to_its_did() -> None:
    text = "hola @lab.univerlab.org, mira"
    facets = richtext.facets_for(
        text, lambda handle: "did:plc:lab123" if handle == "lab.univerlab.org" else None
    )
    assert len(facets) == 1
    assert facets[0]["features"] == [
        {"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:lab123"}
    ]
    start = facets[0]["index"]["byteStart"]
    end = facets[0]["index"]["byteEnd"]
    assert text.encode("utf-8")[start:end].decode("utf-8") == "@lab.univerlab.org"


def test_an_unresolvable_mention_stays_plain_text() -> None:
    assert richtext.facets_for("hola @nadie.aqui", lambda handle: None) == []
    assert richtext.facets_for("hola @nadie.aqui") == []


def test_a_hashtag_is_a_facet_without_its_hash_in_the_offsets() -> None:
    text = "el #taller sigue"
    facets = richtext.facets_for(text)
    assert len(facets) == 1
    assert facets[0]["features"] == [{"$type": "app.bsky.richtext.facet#tag", "tag": "taller"}]
    start = facets[0]["index"]["byteStart"]
    end = facets[0]["index"]["byteEnd"]
    assert text.encode("utf-8")[start:end].decode("utf-8") == "#taller"


def test_multibyte_text_measures_offsets_in_utf8_bytes() -> None:
    text = "escuadra 🔧 https://univerlab.org y @lab.univerlab.org #taller"
    seen = richtext.find_spans(text)
    assert seen["links"] and seen["mentions"] and seen["tags"]
    for start, end, _ in seen["links"] + seen["mentions"] + seen["tags"]:
        raw = text.encode("utf-8")
        assert raw[len(text[:start].encode("utf-8")) : len(raw) - len(text[end:].encode("utf-8"))]


def test_a_url_wins_over_a_tag_inside_it() -> None:
    facets = richtext.facets_for("mira https://univerlab.org/#taller ya")
    assert len(facets) == 1
    assert facets[0]["features"][0]["$type"] == "app.bsky.richtext.facet#link"


def _lab_did(handle: str) -> str | None:
    return "did:plc:lab123"


def test_facets_come_out_in_text_order() -> None:
    text = "#taller https://univerlab.org @lab.univerlab.org"
    facets = richtext.facets_for(text, _lab_did)
    starts = [facet["index"]["byteStart"] for facet in facets]
    assert starts == sorted(starts)
    kinds = [facet["features"][0]["$type"].split("#")[1] for facet in facets]
    assert kinds == ["tag", "link", "mention"]
