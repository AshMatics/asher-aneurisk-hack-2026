"""Shared building blocks: base models, identifiers and the enums every layer uses.

Facts here come from ``slicepoint/docs/data-contract-inventory.md`` section 1, which was
extracted from the hackathon practice parquet. Closed enums list the values observed in
that data; they will need extending once real (non-curated) sources arrive.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION: Literal["0.1.0"] = "0.1.0"
"""Version of the contract this package defines. Bumped on any breaking change."""


class ContractModel(BaseModel):
    """Base for every model in the package.

    Frozen (values never change after validation), rejects unknown keys and rejects
    NaN/inf, because JSON cannot carry them and the POC writer already turned them into
    ``null`` (``json.dumps(allow_nan=False)``).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        populate_by_name=True,
        use_enum_values=False,
        protected_namespaces=(),
    )


class VersionedModel(ContractModel):
    """A top-level payload of the new contract. It always carries ``schema_version``.

    The field is a literal: a payload written against another contract version is rejected
    rather than silently misread.
    """

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION


# --------------------------------------------------------------------------- identifiers

SITE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
SiteId = Annotated[str, StringConstraints(pattern=SITE_ID_PATTERN)]
"""Stable machine slug for a site, e.g. ``hospital_b``. Never a display name."""

OPAQUE_ID_PATTERN = r"^\S(?:.*\S)?$"
OPAQUE_ID_MAX_LENGTH = 128

CaseId = Annotated[
    str, StringConstraints(min_length=1, max_length=OPAQUE_ID_MAX_LENGTH, pattern=OPAQUE_ID_PATTERN)
]
"""Opaque case identifier for new data: non-empty, at most 128 characters, no leading or
trailing whitespace. Sources may use any scheme. The practice data happens to use 16
lowercase hex characters (see :data:`HEX16_PATTERN`), but new data is not held to that."""

PatientId = Annotated[
    str, StringConstraints(min_length=1, max_length=OPAQUE_ID_MAX_LENGTH, pattern=OPAQUE_ID_PATTERN)
]
"""Opaque patient identifier, with the same rules as :data:`CaseId`. It is 16 hex in the
practice data.

Not unique per case: hospital_b has 80 rows and 60 patient ids. The data card says
scans of one patient share it "when the hospital records it reliably", so it is not a
reliable person key on its own.
"""

HEX16_PATTERN = r"^[0-9a-f]{16}$"
"""The hashed id format of the hackathon practice data and the POC (legacy only)."""

SHORT_CASE_ID_PATTERN = r"^[0-9a-f]{8}$"
ShortCaseId = Annotated[str, StringConstraints(pattern=SHORT_CASE_ID_PATTERN)]
"""Legacy POC scan id: the first 8 characters of a 16-hex case id. Not guaranteed unique."""

AGE_BAND_PATTERN = r"^\d0-\d9$"
AgeBand = Annotated[str, StringConstraints(pattern=AGE_BAND_PATTERN)]
"""Decade age band such as ``60-69``. Open set: parquet has 20-29..90-99, the hospital_g
sample JSON also has ``10-19``."""

CheckId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
"""Identifier of a check in the check registry (e.g. ``repeats``)."""

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
"""A float in [0, 1] (shares, proportions, Dice)."""

NonNegativeFloat = Annotated[float, Field(ge=0.0)]


def short_case_id(case_id: str) -> str:
    """Return the legacy 8-character scan id for a 16-hex case id."""
    if not re.fullmatch(HEX16_PATTERN, case_id):
        raise ValueError(f"not a 16-hex case id: {case_id!r}")
    return case_id[:8]


def site_id_from_legacy_hospital_name(name: str) -> str:
    """Map a POC display name (``"Hospital B"``) back to the site slug (``hospital_b``).

    The POC built the display name with ``HOSPITAL_NAME.replace("_", " ").title()``; this
    inverts that for the lowercase directory names used in the practice data. It is a
    best-effort bridge for legacy files only: new payloads carry ``site_id`` directly.
    """
    slug = re.sub(r"\s+", "_", name.strip().lower())
    if not re.fullmatch(SITE_ID_PATTERN, slug):
        raise ValueError(f"cannot derive a site_id from hospital name {name!r}")
    return slug


# --------------------------------------------------------------------------- enums


class Sex(str, Enum):
    """Observed values only (M 252, F 168). No unknown/other category in the data."""

    M = "M"
    F = "F"


class ContrastPhase(str, Enum):
    ARTERIAL = "arterial"
    VENOUS = "venous"
    NON_CONTRAST = "non-contrast"


class SliceThicknessClass(str, Enum):
    """Thickness class. In the data the mapping from ``slice_thickness_mm`` is exact:
    thin < 2 mm (0.6-1.5 observed), standard 2.0-3.75, thick 5.0. The schema does not
    enforce that mapping, because detecting inconsistent metadata is the analysis' job."""

    THIN = "thin"
    STANDARD = "standard"
    THICK = "thick"


class AaaSizeClass(str, Enum):
    """AAA size class as recorded by the hospital.

    It follows the hospital's convention, not the diameter: the 30-54mm class has a
    minimum observed diameter of 25.74 mm (hospital e).
    """

    NONE = "none"
    SMALL = "30-54mm"
    LARGE = ">=55mm"


class ScannerVendor(str, Enum):
    """Observed vendors only (siemens 355, philips 40, ge 16; 9 nulls). Closed for v0;
    expect to extend (e.g. canon) once real sources arrive."""

    SIEMENS = "siemens"
    PHILIPS = "philips"
    GE = "ge"


# --------------------------------------------------------------------------- open value lists
# New-contract models accept values outside the observed set (real sources will have
# them). Known values are normalised to their canonical spelling, and unknown values are
# kept (trimmed, plus lowercased for vendors). Legacy V0 models keep the closed enums above.


def _normalize_sex(value: str) -> str:
    v = value.strip()
    upper = v.upper()
    return upper if upper in {s.value for s in Sex} else v


def _normalize_vendor(value: str) -> str:
    return value.strip().lower()


_OPEN_VALUE = StringConstraints(min_length=1, max_length=64, pattern=OPAQUE_ID_PATTERN)

OpenSex = Annotated[
    str,
    _OPEN_VALUE,
    AfterValidator(_normalize_sex),
    Field(description="Open set. Known: M, F (normalised to upper case); other strings are kept.",
          examples=["M", "F"]),
]

OpenScannerVendor = Annotated[
    str,
    _OPEN_VALUE,
    AfterValidator(_normalize_vendor),
    Field(description="Open set, lowercased. Known: siemens, philips, ge; others (e.g. canon) "
          "are accepted.", examples=["siemens", "philips", "ge"]),
]


class Modality(str, Enum):
    """Input modality of an embedding space."""

    CT = "CT"
    MR = "MR"
    REPORT_TEXT = "report_text"
    OTHER = "other"
