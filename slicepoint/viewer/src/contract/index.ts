// Stable names for the generated contract types. The generated file names some types
// after their position in the schema (`Evidence1`, `WithinTolerance1`); importing them
// through here keeps a schema regeneration from rippling through the view-models.
export type {
  AssessmentResult,
  BinMetricsV0,
  CasesToReview,
  CheckDescriptor,
  CheckResult,
  CheckRun,
  CheckRunState,
  CheckStatus,
  DatasheetComparison,
  DatasheetFindingStatus,
  DiameterAgreement,
  DiceMetricsV0,
  Evidence1 as EvidenceItem,
  PerformanceSummary,
  ReviewCase,
  ReviewReason,
  StepRecord,
  StepState,
  Strata,
  StratumRow,
  ThresholdProfile,
  ToleranceRole,
  TriggerThreshold,
  VariableComparison,
  Verdict,
  VerdictOutcome,
  VerdictOverride,
  WithinTolerance1 as WithinTolerance,
} from "./assessment-result.generated";
export { RESULT_TYPE, SCHEMA_SHA256, SCHEMA_VERSION } from "./schema-meta.generated";
export { validate } from "./validate.generated.js";
export type { ValidationError } from "./validate.generated.js";
