// Sample results bundled into the viewer ("Try a sample"). They were written by
// slicepoint-core from the synthetic hackathon practice data (data/practice), with
// hospital_a as the reference; scripts/make-fixtures.sh regenerates them. They are read
// through the same validation path as a user's file. No real patient data.
// Only these four are bundled; the rest of the fixtures are test-only (./all.ts).
import hospitalAOverride from "./hospital_a_override.json";
import hospitalB from "./hospital_b.json";
import hospitalCScores from "./hospital_c_scores.json";
import hospitalD from "./hospital_d.json";

export interface Sample {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly data: unknown;
}

export const SAMPLES: readonly Sample[] = [
  { id: "hospital_b", title: "Hospital B", description: "NO-GO: repeat scans of the same people, no-answers and size errors.", data: hospitalB },
  {
    id: "hospital_a_override",
    title: "Hospital A, committee override",
    description: "Hospital A against its own reference (a sanity check): BORDERLINE derived, set to GO by an example committee decision.",
    data: hospitalAOverride,
  },
  {
    id: "hospital_d",
    title: "Hospital D with a vendor datasheet",
    description: "NO-GO: patient and scan mix, plus the site tested against the vendor's training-data datasheet.",
    data: hospitalD,
  },
  {
    id: "hospital_c_scores",
    title: "Hospital C with provisional scores",
    description: "Written with --show-provisional-scores, for internal review of the draft scores.",
    data: hospitalCScores,
  },
];

export function findSample(id: string | null | undefined): Sample | undefined {
  return id ? SAMPLES.find((s) => s.id === id) : undefined;
}
