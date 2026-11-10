#!/usr/bin/env bash
# Regenerate the bundled sample results from the synthetic practice data.
# Needs the uv workspace synced (`uv sync --all-packages --all-extras` in slicepoint/) and data/practice.
# Run from anywhere:  slicepoint/viewer/scripts/make-fixtures.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
core="$here/../../core"
out="$here/../src/fixtures"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$core"
py=../.venv/bin/python
data=../../data/practice
cli() { "$py" -m slicepoint_core.cli "$@" >/dev/null || [ $? -eq 3 ]; }
cli reference build --data "$data/hospital_a" --site-id hospital_a --out "$tmp/ref_a"
for h in b c d e; do
  cli assess --data "$data/hospital_$h" --site-id "hospital_$h" --reference-profile "$tmp/ref_a" --out "$out/hospital_$h.json"
done
cli assess --data "$data/hospital_a" --site-id hospital_a --reference-profile "$tmp/ref_a" --out "$out/hospital_a_self.json"
cli assess --data "$data/hospital_c" --site-id hospital_c --site-name "Hospital C (provisional scores)" \
  --reference-profile "$tmp/ref_a" --out "$out/hospital_c_scores.json" --show-provisional-scores
# An example human override, written with the contract's own model (no core change).
"$py" - "$out" <<'PY'
import datetime, sys
from pathlib import Path
from slicepoint_schemas.assessment import AssessmentResult
from slicepoint_schemas.verdict import VerdictOutcome, VerdictOverride
out = Path(sys.argv[1])
r = AssessmentResult.model_validate_json((out / "hospital_a_self.json").read_text())
o = VerdictOverride(
    outcome=VerdictOutcome.GO,
    by="AI governance committee (example)",
    at=datetime.datetime(2026, 11, 9, 15, 30, tzinfo=datetime.timezone.utc),
    note="Example override for the viewer fixture: the size-tolerance watch was reviewed case by case "
         "and accepted for a supervised pilot.",
)
r2 = r.model_copy(update={"verdict": r.verdict.with_override(o), "site_name": "Hospital A (example committee override)"})
AssessmentResult.model_validate(r2.model_dump())
(out / "hospital_a_override.json").write_text(r2.model_dump_json(indent=2, by_alias=True))
PY
echo "Wrote fixtures to $out"
