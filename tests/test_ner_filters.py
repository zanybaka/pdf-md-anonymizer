"""Unit tests for SpanFilter chain and snapshot test for FILTERS ordering (NER-008)."""

from __future__ import annotations

import types

from anonymizer.categories import Category
from anonymizer.detect.ner import (
    FILTERS,
    NerContext,
    _CategoryRouting,
    _LemmaStoplist,
    _OrgLocPropn,
    _PersonPropn,
    _SkillSection,
    _TechStoplist,
)


def _ctx(skill_ranges=None, stoplist=None):
    return NerContext(
        text="",
        skill_ranges=skill_ranges or [],
        stoplist=frozenset(stoplist or []),
    )


def _opts(**kw):
    return types.SimpleNamespace(**kw)


def _span(pos_list):
    """Fake natasha span with tokens having given POS tags covering [0, 1)."""
    tokens = [types.SimpleNamespace(pos=pos, start=0, stop=1) for pos in pos_list]
    return types.SimpleNamespace(tokens=tokens)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_filter_ordering_snapshot():
    assert [f.name for f in FILTERS] == [
        "CategoryRouting",
        "PersonPropn",
        "OrgLocPropn",
        "SkillSection",
        "TechStoplist",
        "LemmaStoplist",
    ]


# ---------------------------------------------------------------------------
# CategoryRouting
# ---------------------------------------------------------------------------


def test_category_routing_drops_org_when_disabled():
    f = _CategoryRouting()
    assert f.keep(None, "Рога и Копыта", 0, 14, Category.ORG, _opts(ner_org=False), _ctx()) is False


def test_category_routing_drops_loc_when_disabled():
    f = _CategoryRouting()
    assert f.keep(None, "Москва", 0, 6, Category.LOC, _opts(ner_loc=False), _ctx()) is False


def test_category_routing_keeps_person_regardless():
    f = _CategoryRouting()
    assert (
        f.keep(None, "Иванов", 0, 6, Category.PERSON, _opts(ner_org=False, ner_loc=False), _ctx())
        is True
    )


def test_category_routing_keeps_org_when_enabled():
    f = _CategoryRouting()
    assert f.keep(None, "Рога и Копыта", 0, 14, Category.ORG, _opts(ner_org=True), _ctx()) is True


# ---------------------------------------------------------------------------
# PersonPropn
# ---------------------------------------------------------------------------


def test_person_propn_drops_when_no_propn():
    f = _PersonPropn()
    span = _span(["NOUN"])
    assert f.keep(span, "Программист", 0, 11, Category.PERSON, _opts(), _ctx()) is False


def test_person_propn_keeps_when_propn_present():
    f = _PersonPropn()
    span = _span(["PROPN"])
    assert f.keep(span, "Иванов", 0, 6, Category.PERSON, _opts(), _ctx()) is True


def test_person_propn_passes_org_unconditionally():
    f = _PersonPropn()
    span = _span(["NOUN"])
    assert f.keep(span, "Компания", 0, 8, Category.ORG, _opts(), _ctx()) is True


# ---------------------------------------------------------------------------
# OrgLocPropn
# ---------------------------------------------------------------------------


def test_org_loc_propn_drops_common_noun_org():
    f = _OrgLocPropn()
    span = _span(["NOUN"])
    assert (
        f.keep(span, "Канцелярия", 0, 10, Category.ORG, _opts(ner_pos_filter=True), _ctx()) is False
    )


def test_org_loc_propn_keeps_when_filter_disabled():
    f = _OrgLocPropn()
    span = _span(["NOUN"])
    assert f.keep(span, "Вокруг", 0, 6, Category.ORG, _opts(ner_pos_filter=False), _ctx()) is True


def test_org_loc_propn_keeps_propn_org():
    f = _OrgLocPropn()
    span = _span(["PROPN"])
    assert f.keep(span, "Газпром", 0, 7, Category.ORG, _opts(ner_pos_filter=True), _ctx()) is True


def test_org_loc_propn_keeps_foreign_org():
    f = _OrgLocPropn()
    span = _span(["X"])
    assert (
        f.keep(span, "Deutsche Bank", 0, 13, Category.ORG, _opts(ner_pos_filter=True), _ctx())
        is True
    )


# ---------------------------------------------------------------------------
# SkillSection
# ---------------------------------------------------------------------------


def test_skill_section_drops_org_in_range():
    f = _SkillSection()
    ctx = _ctx(skill_ranges=[(10, 50)])
    assert f.keep(None, "Python", 15, 21, Category.ORG, _opts(), ctx) is False


def test_skill_section_keeps_org_outside_range():
    f = _SkillSection()
    ctx = _ctx(skill_ranges=[(10, 50)])
    assert f.keep(None, "Газпром", 5, 12, Category.ORG, _opts(), ctx) is True


def test_skill_section_passes_person_in_range():
    f = _SkillSection()
    ctx = _ctx(skill_ranges=[(0, 100)])
    assert f.keep(None, "Иванов", 5, 11, Category.PERSON, _opts(), ctx) is True


# ---------------------------------------------------------------------------
# TechStoplist
# ---------------------------------------------------------------------------


def test_tech_stoplist_drops_known_tool_as_org():
    f = _TechStoplist()
    # "python" is a known tech term
    assert f.keep(None, "Python", 0, 6, Category.ORG, _opts(), _ctx()) is False


def test_tech_stoplist_drops_known_tool_as_person():
    f = _TechStoplist()
    assert f.keep(None, "Python", 0, 6, Category.PERSON, _opts(), _ctx()) is False


def test_tech_stoplist_passes_loc():
    f = _TechStoplist()
    # LOC is not checked by this filter
    assert f.keep(None, "Python", 0, 6, Category.LOC, _opts(), _ctx()) is True


def test_tech_stoplist_passes_unknown_term():
    f = _TechStoplist()
    assert f.keep(None, "Газпром", 0, 7, Category.ORG, _opts(), _ctx()) is True


# ---------------------------------------------------------------------------
# LemmaStoplist
# ---------------------------------------------------------------------------


def test_lemma_stoplist_drops_term_in_stoplist():
    f = _LemmaStoplist()
    ctx = _ctx(stoplist=["газпром"])
    assert f.keep(None, "газпром", 0, 7, Category.ORG, _opts(), ctx) is False


def test_lemma_stoplist_keeps_unknown_term():
    f = _LemmaStoplist()
    ctx = _ctx(stoplist=["someone"])
    assert f.keep(None, "Иванов", 0, 6, Category.PERSON, _opts(), ctx) is True
