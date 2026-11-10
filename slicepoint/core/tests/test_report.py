"""The self-contained HTML report (milestone 2)."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest
from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE
from slicepoint_schemas.assessment import ReviewReason, ScanSummary
from slicepoint_schemas.thresholds import DiceMarkers

from conftest import FIXED_NOW, load_site, needs_data
from slicepoint_core import Assessment, AssessmentReport, ReferenceProfile, TabularDataset, render_html
from slicepoint_core.report import (
    DISCLAIMER,
    _readable,
    display_site_name,
    format_n_effective,
    humanize_column,
    summarize,
)
from slicepoint_core.strata import cases_to_review, stratified_table

pytestmark = needs_data


class _Collector(HTMLParser):
    """Collects tags, attributes and heading text, and checks the markup nests properly."""

    VOID = {"meta", "link", "br", "img", "hr", "input", "line", "circle", "rect", "path"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.headings: list[tuple[str, str]] = []
        self._h: str | None = None
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        if tag in ("h1", "h2", "h3"):
            self._h = tag
            self.headings.append((tag, ""))
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> with open {self.stack[-3:]}")
            return
        self.stack.pop()
        if tag == self._h:
            self._h = None

    def handle_data(self, data: str) -> None:
        if self._h is not None and self.headings:
            t, text = self.headings[-1]
            self.headings[-1] = (t, text + data)


def _parse(doc: str) -> _Collector:
    c = _Collector()
    c.feed(doc)
    c.close()
    return c


@pytest.fixture(scope="module")
def report_b(reference: ReferenceProfile) -> AssessmentReport:
    return Assessment(load_site("hospital_b"), reference, HACKATHON_DEFAULT_PROFILE, now=FIXED_NOW).run()


@pytest.fixture(scope="module")
def html_b(report_b: AssessmentReport) -> str:
    return render_html(report_b)


def test_no_external_resources(html_b: str, report_b: AssessmentReport) -> None:
    for doc in (html_b, render_html(report_b, show_provisional_scores=True)):
        assert "http://" not in doc and "https://" not in doc
        assert not re.search(r"""(src|href)\s*=\s*["']//""", doc)  # protocol-relative
        parsed = _parse(doc)
        assert not [t for t, a in parsed.tags if t in ("script", "link", "img", "iframe", "object", "embed")]
        assert not [a for t, a in parsed.tags if "src" in a]
        assert "@import" not in doc and "url(" not in doc
        assert "default-src 'none'" in doc  # CSP forbids network loads


def test_markup_is_well_formed_and_accessible(html_b: str) -> None:
    parsed = _parse(html_b)
    assert parsed.errors == [] and parsed.stack == []
    assert [t for t, _ in parsed.headings].count("h1") == 1
    h2 = [text.strip() for t, text in parsed.headings if t == "h2"]
    assert h2 == ["Verdict", "Health checks", "AI performance on your sample", "Results by group",
                  "Cases to review", "Notes from the run", "Methods and limits", "Provenance"]
    assert '<html lang="en">' in html_b
    # every chart has an accessible name
    svgs = [a for t, a in parsed.tags if t == "svg"]
    assert svgs and all(a.get("role") == "img" and a.get("aria-label") for a in svgs)


def test_verdict_comes_first_with_rationale(html_b: str) -> None:
    assert html_b.index('id="verdict"') < html_b.index('id="checks"')
    assert "NO-GO" in html_b
    assert "2 of 5 checks found a problem (Different people, AI accuracy)" in html_b


def test_each_check_card_present_with_n_and_sub_factors(html_b: str, report_b: AssessmentReport) -> None:
    for check_id, res in report_b.checks.items():
        m = re.search(rf'<article class="card" id="check-{check_id}".*?</article>', html_b, re.S)
        assert m, check_id
        card = m.group(0)
        assert f"Based on {res.n} scans" in card
        assert res.n_effective is not None and f"effective n {format_n_effective(res.n_effective)}" in card
        assert "What this means:" in card
        # status is a text label, never colour alone
        assert {"ok": "OK", "watch": "Watch", "problem": "Problem"}[res.status.value] in card
    repeats = re.search(r'id="check-repeats".*?</article>', html_b, re.S)
    assert repeats and "People" in repeats.group(0) and "Random vs by-person split leakage" in repeats.group(0)


def test_provisional_scores_hidden_by_default(html_b: str, report_b: AssessmentReport) -> None:
    assert "provisional-v0" not in html_b
    assert "Provisional score" not in html_b
    assert 'id="provisional-banner"' not in html_b
    assert "score_part" not in html_b and "score_basis" not in html_b
    shown = render_html(report_b, show_provisional_scores=True)
    assert 'id="provisional-banner"' in shown and "not validated" in shown
    assert shown.count("Provisional score:") == 5
    assert "Provisional score: <strong>50</strong> / 100 (target 90)" in shown  # repeats: 40 people / 80 scans


def test_disclaimer_and_provenance(html_b: str, report_b: AssessmentReport) -> None:
    assert DISCLAIMER == ("Results come from a test sample, not a full trial. "
                          "This report supports a decision and is not medical advice.")
    assert DISCLAIMER in html_b
    r = report_b.result
    for text in (r.site_id, r.reference.reference_id, r.profile_id, r.schema_version, r.generated_at.isoformat()):
        assert text in html_b
    # the segmentation step is always skipped in milestone 1/2 and must be shown as such
    assert '<tr class="step-skipped"><th scope="row"><code>segmentation</code>' in html_b


def test_performance_two_ways_with_wilson_and_profile_tolerances(html_b: str) -> None:
    assert "Missing counts as wrong (primary)" in html_b and "When answered" in html_b
    assert "86% (6/7); 95% CI 49% to 97%" in html_b
    assert "Within 2 mm (agreement tolerance from the profile)" in html_b
    assert "Within 3 mm (size tolerance from the profile)" in html_b
    assert "basic 0.81" in html_b and "clinical 0.90" in html_b


def test_skipped_checks_render_as_not_evaluated(reference: ReferenceProfile) -> None:
    site = load_site("hospital_d")
    frame = site.frame.drop(columns=["max_aortic_diameter_mm", "aaa", "aaa_size_class"])
    no_labels = TabularDataset(site_id=site.site_id, frame=frame, embeddings=site.embeddings, space=site.space,
                               has_labels=False)
    rep = Assessment(no_labels, reference, now=FIXED_NOW).run()
    doc = render_html(rep)
    for cid in ("labels", "accuracy"):
        card = re.search(rf'id="check-{cid}".*?</article>', doc, re.S)
        assert card and "Not evaluated" in card.group(0) and "missing input: labels" in card.group(0)
    assert "<strong>Not evaluated:</strong>" in doc
    assert '<tr class="step-skipped"><th scope="row"><code>check_labels</code>' in doc
    assert '<tr class="step-skipped"><th scope="row"><code>performance</code>' in doc
    checks = summarize(rep)["checks"]
    assert isinstance(checks, list)
    statuses = {c["id"]: c["status"] for c in checks}
    assert statuses["labels"] == "skipped" and statuses["accuracy"] == "skipped"


def test_stratified_table_suppresses_small_groups(report_b: AssessmentReport) -> None:
    st = stratified_table(report_b.result.scans, size_tolerance_mm=3.0, min_group_size=15,
                          min_aaa_for_sensitivity=3)
    rows = st.rows
    thick = next(r for r in rows if r.variable == "slice_thickness_class" and r.level == "thick")
    assert thick.too_few and thick.mae_mm is None and thick.sens is None
    venous = next(r for r in rows if r.variable == "contrast_phase" and r.level == "venous")
    assert not venous.too_few and venous.n == 46 and venous.sens is not None
    assert sum(r.n for r in rows if r.variable == "sex") == len(report_b.result.scans)


def test_cases_to_review_puts_missed_aneurysms_first(report_b: AssessmentReport) -> None:
    cases = cases_to_review(report_b.result.scans, size_tolerance_mm=3.0).cases
    assert cases[0].reasons[0] is ReviewReason.MISSED_ANEURYSM
    no_answer = (ReviewReason.NO_ANSWER, ReviewReason.NO_ANSWER_ON_ANEURYSM)
    assert sum(1 for c in cases if any(r in no_answer for r in c.reasons)) == 4
    s = ScanSummary(case_id="x", person_group="p0", aaa=False, ai_aaa=False, reference_diameter_mm=20.0,
                    ai_diameter_mm=21.0)
    assert cases_to_review([s], size_tolerance_mm=3.0).cases == ()


def test_strata_and_cases_are_in_the_result(report_b: AssessmentReport) -> None:
    """The runner computes both tables and stores them in the contract result."""
    r = report_b.result
    assert r.strata is not None and r.cases_to_review is not None
    assert r.strata == stratified_table(r.scans, size_tolerance_mm=3.0, min_group_size=15, min_aaa_for_sensitivity=3)
    assert r.cases_to_review == cases_to_review(r.scans, size_tolerance_mm=3.0)
    assert (r.strata.min_group_size, r.strata.min_aaa_for_sensitivity, r.strata.size_tolerance_mm) == (15, 3, 3.0)
    assert r.cases_to_review.n_scans == len(r.scans) == 80
    steps = {s.step: s.state.value for s in r.steps}
    assert steps["strata"] == "ok" and steps["cases_to_review"] == "ok"
    assert "strata" in report_b.to_json() and "cases_to_review" in report_b.to_json()


def test_renderer_displays_the_stored_tables_without_recomputing(
    report_b: AssessmentReport, monkeypatch: pytest.MonkeyPatch
) -> None:
    import slicepoint_core.stats as stats_mod
    import slicepoint_core.strata as strata_mod

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("the renderer must not compute statistics")

    for name in ("diameter_agreement", "binary_metrics"):
        monkeypatch.setattr(stats_mod, name, forbidden)
    for name in ("stratified_table", "cases_to_review"):
        monkeypatch.setattr(strata_mod, name, forbidden)
    doc = render_html(report_b)
    assert "Too few (fewer than 15 scans)" in doc and "Missed aneurysm" in doc
    # Change the stored table: the page follows the result, not a recomputation.
    r = report_b.result
    assert r.strata is not None
    first = r.strata.rows[0].model_copy(update={"level": "zz-stored-level"})
    edited = r.model_copy(update={"strata": r.strata.model_copy(update={"rows": (first, *r.strata.rows[1:])})})
    assert "zz-stored-level" in render_html(edited)


def test_thresholds_are_recorded_and_the_renderer_uses_them(report_b: AssessmentReport) -> None:
    r = report_b.result
    assert r.thresholds == HACKATHON_DEFAULT_PROFILE and r.thresholds.profile_id == r.profile_id
    assert '"thresholds"' in report_b.to_json() and '"min_group_size": 15' in report_b.to_json()
    # The page reads markers, decision line and group rules from the result's own thresholds.
    custom = HACKATHON_DEFAULT_PROFILE.model_copy(update={"dice_markers": DiceMarkers(lower=0.72, upper=0.93)})
    assert r.strata is not None
    strata = r.strata.model_copy(update={"min_group_size": 21, "min_aaa_for_sensitivity": 5})
    doc = render_html(r.model_copy(update={"thresholds": custom, "strata": strata}))
    assert "basic 0.72" in doc and "clinical 0.93" in doc and "basic 0.81" not in doc
    assert "Groups with fewer than 21 scans" in doc and "at least 5 aneurysms" in doc


def test_result_without_thresholds_says_not_recorded(report_b: AssessmentReport) -> None:
    """No fallback: an older result without thresholds or tables never gets defaults."""
    bare = report_b.result.model_copy(update={"thresholds": None, "strata": None, "cases_to_review": None})
    doc = render_html(bare)
    assert "not recorded in this result" in doc
    assert "fewer than 15 scans" not in doc and "basic 0.81" not in doc
    assert "decision line not recorded" in doc
    assert _parse(doc).errors == []


def test_title_uses_site_name_or_humanized_id(reference: ReferenceProfile, html_b: str) -> None:
    assert display_site_name("hospital_b") == "Hospital B"
    assert display_site_name("st-marys_east") == "St Marys East"
    assert display_site_name("hospital_b", "  St. Mary's  ") == "St. Mary's"
    assert "<h1>SlicePoint fit check: Hospital B</h1>" in html_b
    assert "<title>SlicePoint report: Hospital B</title>" in html_b
    named = Assessment(load_site("hospital_b"), reference, now=FIXED_NOW, site_name="St. Mary's Hospital").run()
    assert named.result.site_name == "St. Mary's Hospital"
    assert '"site_name": "St. Mary\'s Hospital"' in named.to_json()
    doc = render_html(named)
    assert "<h1>SlicePoint fit check: St. Mary&#x27;s Hospital</h1>" in doc
    assert "hospital_b" in doc  # the id is still in the provenance


def test_effective_n_is_whole_when_whole(html_b: str) -> None:
    assert format_n_effective(32.0) == "32" and format_n_effective(31.44) == "31.4"
    assert format_n_effective(1234.0) == "1,234"
    assert "effective n 32.0" not in html_b
    assert re.search(r"from 40 people; effective n 32\.</p>", html_b)


def test_findings_name_groups_in_words(reports: dict[str, AssessmentReport]) -> None:
    assert humanize_column("contrast_phase") == "Contrast phase"
    assert humanize_column("kvp_bucket_class") == "Kvp bucket class"
    raw = "Problem 'many no-answers' in: contrast_phase=arterial (n=16), age_band=70-79 (n=1), new_col=x (n=20)."
    assert _readable(raw) == ("Problem 'many no-answers' in: Contrast phase: arterial (16 cases), "
                              "Age group: 70-79 (1 case), New col: x (20 cases).")
    assert _readable("tested: contrast_phase=arterial, sex=F.") == "tested: Contrast phase: arterial, Sex: F."
    assert _readable("vs 9% at the reference (p=0.004)") == "vs 9% at the reference (p=0.004)"
    docs = "".join(render_html(r) for r in reports.values())
    assert "Contrast phase: arterial (16 cases)" in docs
    assert "=arterial" not in docs and "(n=" not in docs


def test_notebook_iframe_is_isolated(report_b: AssessmentReport) -> None:
    frag = report_b.to_notebook_html(height_px=500)
    assert frag.startswith("<iframe") and 'sandbox=""' in frag and "srcdoc=" in frag
    assert "<style>" not in frag  # escaped inside srcdoc, so it cannot restyle the notebook


def test_self_comparison_warning_next_to_the_verdict(reference: ReferenceProfile, html_b: str) -> None:
    from slicepoint_core import SELF_COMPARISON_NOTE

    own = Assessment(load_site("hospital_a"), reference, HACKATHON_DEFAULT_PROFILE, now=FIXED_NOW).run()
    doc = render_html(own)
    verdict = doc[doc.index('<section id="verdict"'):doc.index("</section>", doc.index('<section id="verdict"'))]
    assert 'id="self-comparison"' in verdict and SELF_COMPARISON_NOTE in verdict
    assert SELF_COMPARISON_NOTE in doc[doc.index('<section id="notes"'):]
    assert summarize(own)["self_comparison"] is True
    assert 'id="self-comparison"' not in html_b
    assert _parse(doc).errors == []


def test_titles_come_from_the_result_descriptors(report_b: AssessmentReport) -> None:
    r = report_b.result
    assert r.check_descriptors is not None
    renamed = tuple(d.model_copy(update={"title": "Scanner fit (from the result)"}) if d.id == "scanning" else d
                    for d in r.check_descriptors)
    doc = render_html(r.model_copy(update={"check_descriptors": renamed}))
    assert "Scanner fit (from the result)" in doc and ">Scan settings match<" not in doc
    checks = summarize(r.model_copy(update={"check_descriptors": renamed}))["checks"]
    assert isinstance(checks, list)
    assert {c["id"]: c["title"] for c in checks}["scanning"] == "Scanner fit (from the result)"


def test_result_without_descriptors_falls_back_to_the_default_registry(report_b: AssessmentReport) -> None:
    older = report_b.result.model_copy(update={"check_descriptors": None})
    assert render_html(older) == render_html(report_b.result)
