"""What a vendor discloses about the data its model was built on.

A :class:`VendorDatasheet` holds summary statistics, never rows: the share of men and
women, scanner makers, contrast phases, an age mean and SD or median and IQR, a histogram
read off a paper's figure. A hospital fills one in from a 510(k) summary, a paper, a model
card or a sales deck, and SlicePoint tests its own data against it.

Design rules:

* **Marginals only.** Each variable is summarised on its own. Vendors almost never publish
  joint distributions, and inventing them would be worse than not having them.
* **Every number says where it came from.** Each variable cites at least one source and
  says how the value was obtained (:class:`ValueSource`): reported in the text or a table,
  computed from published row-level data, digitized from a figure, or estimated. Checks
  can treat a digitized histogram more loosely than a reported table.
* **The population is explicit.** :class:`PopulationScope` says what the numbers
  describe (e.g. "all CT, every body region" versus "adult abdominal CT"). When the scope
  is wider than the site's, a difference in distribution is expected and is not by itself
  a problem; the coverage question (is the site inside what the model saw?) still applies.
* **Sample sizes travel with the numbers**, so a check can tell a 40-scan datasheet from a
  4,000-scan one.

The checks that use a datasheet live in the analysis core. This module only validates
that a datasheet is internally consistent.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .common import ContractModel, Modality, NonNegativeFloat, Sha256Hex, SiteId, UnitInterval, VersionedModel

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")]
"""Machine identifier: lowercase letters, digits, ``_``, ``.``, ``-``; at most 64."""

VariableName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
"""Variable identifier. Use a name from :data:`KNOWN_VARIABLES` when one fits, so checks
can match it to a site column; other names are accepted and reported but not tested."""

Text = Annotated[str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]

PROPORTION_SUM_TOLERANCE = 0.03
"""How far category shares may sum from 1. Published percentages are rounded (five
categories at whole percent can be off by 2.5 points) and digitized bars are approximate."""

COUNT_PROPORTION_TOLERANCE = 0.01
"""How far a stated share may sit from ``count / total`` when both are given."""


class ValueSource(str, Enum):
    """How a number got into the datasheet."""

    REPORTED = "reported"
    """Stated as a number in the source's text or a table."""
    COMPUTED = "computed"
    """Computed from row-level data the source published (e.g. a dataset's metadata file)."""
    DIGITIZED = "digitized"
    """Read off a figure. Approximate; checks should allow for reading error."""
    ESTIMATED = "estimated"
    """Inferred or assumed by whoever filled in the datasheet; the weakest kind."""


class SourceKind(str, Enum):
    PUBLICATION = "publication"
    REGULATORY_SUMMARY = "regulatory_summary"
    """e.g. an FDA 510(k) or De Novo summary."""
    MODEL_CARD = "model_card"
    VENDOR_DOCUMENT = "vendor_document"
    """Instructions for use, white paper, sales or onboarding material."""
    DATASET_RELEASE = "dataset_release"
    OTHER = "other"


class DatasheetPartition(str, Enum):
    """Which part of the vendor's data the datasheet describes."""

    TRAINING = "training"
    VALIDATION = "validation"
    TEST = "test"
    DEVELOPMENT = "development"
    """Training, validation and test together (or the source does not separate them)."""
    UNSPECIFIED = "unspecified"


class DatasheetSource(ContractModel):
    """A document the datasheet draws numbers from."""

    source_id: Slug
    kind: SourceKind
    citation: Text
    url: Annotated[str, StringConstraints(pattern=r"^https?://\S+$", max_length=500)] | None = None
    doi: Annotated[str, StringConstraints(pattern=r"^10\.\d{4,9}/\S+$")] | None = None
    accessed: dt.date | None = None


class SourceRef(ContractModel):
    """Where in a source a variable's numbers come from, and how they were obtained."""

    source_id: Slug
    value_source: ValueSource
    locator: ShortText | None = Field(default=None, examples=["Figure 3", "Table 1", "Section 7.2"])
    note: Text | None = None


class PopulationScope(ContractModel):
    """What population the datasheet's numbers describe.

    ``description`` is required and is what a person reads. The structured fields are
    optional; checks use them, when present, to warn that a site and a datasheet describe
    different populations.
    """

    description: Text
    modality: Modality | None = None
    body_regions: tuple[ShortText, ...] = Field(default=(), examples=[("abdomen", "pelvis")])
    age_range_years: tuple[NonNegativeFloat, NonNegativeFloat] | None = None
    study_period: ShortText | None = Field(default=None, examples=["2012, 2016 and 2020"])
    n_sites: int | None = Field(default=None, ge=1)
    countries: tuple[ShortText, ...] = ()
    inclusion: tuple[Text, ...] = ()
    exclusion: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def _age_range_ordered(self) -> PopulationScope:
        if self.age_range_years is not None and self.age_range_years[0] > self.age_range_years[1]:
            raise ValueError("age_range_years must be (low, high)")
        return self


# --------------------------------------------------------------------------- summaries


def _close(a: float, b: float, tol: float) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


class Histogram(ContractModel):
    """Binned distribution: ``len(edges) == len(bins) + 1``, edges strictly increasing.

    Give ``counts`` or ``proportions`` (or both). Counts may be fractional, since bars
    read off a figure rarely land on whole numbers.
    """

    edges: tuple[float, ...] = Field(min_length=2)
    counts: tuple[NonNegativeFloat, ...] | None = None
    proportions: tuple[UnitInterval, ...] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Histogram:
        if any(b <= a for a, b in zip(self.edges, self.edges[1:])):
            raise ValueError("histogram edges must be strictly increasing")
        bins = len(self.edges) - 1
        if self.counts is None and self.proportions is None:
            raise ValueError("histogram needs counts or proportions")
        for name, values in (("counts", self.counts), ("proportions", self.proportions)):
            if values is not None and len(values) != bins:
                raise ValueError(f"histogram has {bins} bins but {len(values)} {name}")
        if self.counts is not None and sum(self.counts) <= 0:
            raise ValueError("histogram counts are all zero")
        if self.proportions is not None and not _close(sum(self.proportions), 1.0, PROPORTION_SUM_TOLERANCE):
            raise ValueError(f"histogram proportions sum to {sum(self.proportions):.3f}, not 1")
        if self.counts is not None and self.proportions is not None:
            total = sum(self.counts)
            if any(not _close(c / total, p, COUNT_PROPORTION_TOLERANCE) for c, p in zip(self.counts, self.proportions)):
                raise ValueError("histogram counts and proportions disagree")
        return self

    def shares(self) -> tuple[float, ...]:
        """Bin shares summing to exactly 1 (counts preferred over rounded proportions)."""
        values = self.counts if self.counts is not None else self.proportions
        assert values is not None
        total = sum(values)
        return tuple(v / total for v in values)


class ContinuousSummary(ContractModel):
    """A numeric variable (age, kVp, slice thickness, diameter).

    Needs at least one description of shape: mean with SD, median with IQR (``q1`` and
    ``q3``), or a histogram. ``min`` and ``max`` alone are not enough to test against, but
    they matter for the coverage question, so give them whenever the source does.
    """

    kind: Literal["continuous"] = "continuous"
    unit: ShortText = Field(examples=["years", "kV", "mm"])
    mean: float | None = None
    sd: NonNegativeFloat | None = None
    median: float | None = None
    q1: float | None = None
    q3: float | None = None
    min: float | None = None
    max: float | None = None
    histogram: Histogram | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ContinuousSummary:
        if self.sd is not None and self.mean is None:
            raise ValueError("sd given without mean")
        if (self.q1 is None) != (self.q3 is None):
            raise ValueError("give q1 and q3 together (the IQR)")
        has_moments = self.mean is not None and self.sd is not None
        has_quartiles = self.median is not None and self.q1 is not None
        if not (has_moments or has_quartiles or self.histogram is not None):
            raise ValueError("continuous summary needs mean and sd, median and IQR, or a histogram")
        ordered = [v for v in (self.min, self.q1, self.median, self.q3, self.max) if v is not None]
        if any(b < a for a, b in zip(ordered, ordered[1:])):
            raise ValueError("min <= q1 <= median <= q3 <= max is violated")
        if self.mean is not None:
            if self.min is not None and self.mean < self.min:
                raise ValueError("mean is below min")
            if self.max is not None and self.mean > self.max:
                raise ValueError("mean is above max")
        return self


class CategoricalSummary(ContractModel):
    """A categorical variable (sex, scanner maker, contrast phase, AAA yes/no).

    Keys are category labels as the source writes them; keep ``unknown`` or ``other`` as
    categories when the source reports them. Give ``counts``, ``proportions`` or both.
    """

    kind: Literal["categorical"] = "categorical"
    counts: dict[ShortText, NonNegativeFloat] | None = None
    proportions: dict[ShortText, UnitInterval] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> CategoricalSummary:
        if self.counts is None and self.proportions is None:
            raise ValueError("categorical summary needs counts or proportions")
        if self.counts is not None:
            if not self.counts:
                raise ValueError("counts is empty")
            if sum(self.counts.values()) <= 0:
                raise ValueError("counts are all zero")
        if self.proportions is not None:
            if not self.proportions:
                raise ValueError("proportions is empty")
            total = sum(self.proportions.values())
            if not _close(total, 1.0, PROPORTION_SUM_TOLERANCE):
                raise ValueError(f"proportions sum to {total:.3f}, not 1")
        if self.counts is not None and self.proportions is not None:
            if set(self.counts) != set(self.proportions):
                raise ValueError("counts and proportions name different categories")
            n = sum(self.counts.values())
            for k, p in self.proportions.items():
                if not _close(self.counts[k] / n, p, COUNT_PROPORTION_TOLERANCE):
                    raise ValueError(f"category {k!r}: count share {self.counts[k] / n:.3f} vs proportion {p:.3f}")
        return self

    def shares(self) -> dict[str, float]:
        """Category shares summing to exactly 1 (counts preferred over rounded proportions)."""
        values = self.counts if self.counts is not None else self.proportions
        assert values is not None
        total = sum(values.values())
        return {k: v / total for k, v in values.items()}


Summary = Annotated[ContinuousSummary | CategoricalSummary, Field(discriminator="kind")]


KNOWN_VARIABLES: Mapping[str, tuple[Literal["continuous", "categorical"], str]] = {
    "age_years": ("continuous", "Patient age in years. Sites with only `age_band` are compared by band."),
    "sex": ("categorical", "`features.sex`."),
    "scanner_vendor": ("categorical", "`features.scanner_vendor` (manufacturer)."),
    "scanner_model": ("categorical", "Scanner model name."),
    "contrast_phase": ("categorical", "`features.contrast_phase`: arterial, venous, non-contrast."),
    "contrast_agent": ("categorical", "Contrast given or not (yes / no)."),
    "slice_thickness_mm": ("continuous", "`features.slice_thickness_mm`."),
    "slice_thickness_class": ("categorical", "`features.slice_thickness_class`: thin, standard, thick."),
    "kvp": ("continuous", "`features.kvp`, tube voltage."),
    "tube_current_ma": ("continuous", "Tube current in mA."),
    "study_type": ("categorical", "Study or protocol type as the source groups it."),
    "body_region": ("categorical", "Body region scanned."),
    "race": ("categorical", "Race as the source reports it (categories vary by country and source)."),
    "ethnicity": ("categorical", "Ethnicity as the source reports it (e.g. Hispanic or Latino / not)."),
    "site": ("categorical", "Contributing site or institute (codes are the source's own)."),
    "pathology": ("categorical", "Main pathology group as the source reports it."),
    "max_aortic_diameter_mm": ("continuous", "`labels.max_aortic_diameter_mm`."),
    "aaa": ("categorical", "`labels.aaa` as true / false (AAA prevalence)."),
    "aaa_size_class": ("categorical", "`labels.aaa_size_class`."),
}
"""Variable names checks know how to match to a site, with the summary kind each must use."""


class DatasheetVariable(ContractModel):
    """One disclosed variable: its summary, how many scans it covers, and its sources."""

    variable: VariableName
    label: ShortText | None = Field(default=None, description="Display name, e.g. as the source words it.")
    summary: Summary
    n: int | None = Field(default=None, ge=1, description="Scans the summary is based on.")
    n_missing: int | None = Field(default=None, ge=0, description="Scans with no value for this variable.")
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    note: Text | None = None

    @model_validator(mode="after")
    def _known_kind(self) -> DatasheetVariable:
        known = KNOWN_VARIABLES.get(self.variable)
        if known is not None and known[0] != self.summary.kind:
            raise ValueError(f"{self.variable} must be a {known[0]} summary, got {self.summary.kind}")
        return self

    @property
    def weakest_value_source(self) -> ValueSource:
        """The least direct way any of this variable's numbers was obtained."""
        order = list(ValueSource)
        return max((s.value_source for s in self.sources), key=order.index)


class ModelIdentity(ContractModel):
    """The model the datasheet is about."""

    name: ShortText
    version: ShortText | None = None
    manufacturer: ShortText | None = None
    intended_use: Text | None = None
    regulatory_ids: tuple[ShortText, ...] = Field(default=(), examples=[("K231234",)])


class VendorDatasheet(VersionedModel):
    """A vendor's disclosed summary of the data behind a model (versioned top-level payload)."""

    datasheet_id: Slug
    title: ShortText
    datasheet_version: ShortText | None = Field(
        default=None, description="Revision of the datasheet itself, e.g. the document's date or version."
    )
    model: ModelIdentity
    describes: DatasheetPartition
    scope: PopulationScope
    n_scans: int | None = Field(default=None, ge=1)
    n_patients: int | None = Field(default=None, ge=1)
    sources: tuple[DatasheetSource, ...] = Field(min_length=1)
    variables: tuple[DatasheetVariable, ...] = Field(min_length=1)
    not_disclosed: tuple[ShortText, ...] = Field(
        default=(), description="What the source does not give, e.g. 'joint distributions', 'scanner models'."
    )
    notes: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> VendorDatasheet:
        ids = [s.source_id for s in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("source_id is not unique")
        names = [v.variable for v in self.variables]
        if len(set(names)) != len(names):
            raise ValueError("variable is listed twice")
        for v in self.variables:
            for ref in v.sources:
                if ref.source_id not in ids:
                    raise ValueError(f"{v.variable}: unknown source_id {ref.source_id!r}")
            if self.n_scans is not None and v.n is not None and v.n + (v.n_missing or 0) > self.n_scans:
                raise ValueError(f"{v.variable}: n + n_missing exceeds n_scans")
        if self.n_scans is not None and self.n_patients is not None and self.n_patients > self.n_scans:
            raise ValueError("n_patients exceeds n_scans")
        return self

    def variable(self, name: str) -> DatasheetVariable | None:
        return next((v for v in self.variables if v.variable == name), None)


# --------------------------------------------------------------------------- comparison result

DATASHEET_COMPARISON_FORMAT: Literal["slicepoint.datasheet_comparison/0.1"] = "slicepoint.datasheet_comparison/0.1"
"""Format tag of :class:`DatasheetComparison`, the result of testing a site against a datasheet."""


class DatasheetFindingStatus(str, Enum):
    OUTSIDE_COVERAGE = "outside_coverage"
    """More of the site lies outside what the datasheet discloses than the tolerance allows."""
    DIFFERS = "differs"
    """Covered, but distributed differently (significant and larger than the minimum effect)."""
    DIFFERS_EXPECTED = "differs_expected"
    """Distributed differently, but the datasheet's scope is broader than the site's."""
    SIMILAR = "similar"
    NOT_TESTABLE = "not_testable"


class CoverageResult(ContractModel):
    outside_n: int = Field(ge=0)
    outside_share: float = Field(ge=0.0, le=1.0)
    detail: str


class EqualityResult(ContractModel):
    method: str
    statistic: float | None = None
    df: float | None = None
    p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    effect_name: Literal["tvd", "smd"]
    effect: float | None = None
    approximate: bool = Field(description="True when the expected distribution was derived, not disclosed, "
                                          "or the datasheet's numbers were digitized or estimated.")
    site_shares: dict[str, float] | None = None
    datasheet_shares: dict[str, float] | None = None
    notes: tuple[str, ...] = ()


class VariableComparison(ContractModel):
    variable: str
    label: str | None = None
    site_column: str | None = None
    status: DatasheetFindingStatus
    reason: str | None = Field(default=None, description="Why not testable, or what drove the status.")
    n_site: int = Field(ge=0, description="Site scans with a value.")
    n_site_missing: int = Field(ge=0)
    datasheet_n: int | None = None
    value_source: ValueSource
    coverage: CoverageResult | None = None
    equality: EqualityResult | None = None


class DatasheetComparison(ContractModel):
    """Result of comparing one site with one vendor datasheet."""

    format: Literal["slicepoint.datasheet_comparison/0.1"] = DATASHEET_COMPARISON_FORMAT
    site_id: SiteId
    n_site_scans: int = Field(ge=0)
    dataset_fingerprint: Sha256Hex
    datasheet_id: str
    datasheet_title: str
    model_name: str
    describes: str
    scope: str
    scope_broader: bool
    params: dict[str, float]
    variables: tuple[VariableComparison, ...]
    not_disclosed: tuple[str, ...] = Field(description="What the datasheet says it does not give.")
    site_columns_not_in_datasheet: tuple[str, ...]
    notes: tuple[str, ...] = ()
    produced_by: str

    def by_status(self, status: DatasheetFindingStatus) -> list[VariableComparison]:
        return [v for v in self.variables if v.status is status]
