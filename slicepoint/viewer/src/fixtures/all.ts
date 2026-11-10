// Every fixture, for tests only. The app imports ./index.ts (three bundled samples), so
// these extra files never reach the built viewer.
import hospitalASelf from "./hospital_a_self.json";
import hospitalC from "./hospital_c.json";
import hospitalD from "./hospital_d.json";
import hospitalE from "./hospital_e.json";
import { SAMPLES, type Sample } from "./index";

export const ALL_FIXTURES: readonly Sample[] = [
  ...SAMPLES,
  { id: "hospital_c", title: "Hospital C", description: "NO-GO: contrast and slice thickness.", data: hospitalC },
  { id: "hospital_d", title: "Hospital D", description: "NO-GO: patient and scan mix.", data: hospitalD },
  { id: "hospital_e", title: "Hospital E", description: "NO-GO: 30 mm rule; missed aneurysms.", data: hospitalE },
  { id: "hospital_a_self", title: "Hospital A vs itself", description: "BORDERLINE self-comparison.", data: hospitalASelf },
];

export function findFixture(id: string): Sample | undefined {
  return ALL_FIXTURES.find((s) => s.id === id);
}
