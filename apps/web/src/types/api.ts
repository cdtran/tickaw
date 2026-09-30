/** Generated or manually maintained API types. */

export type ResultLogicalType =
  | "text"
  | "integer"
  | "number"
  | "boolean"
  | "date"
  | "timestamp"
  | "timestamp_tz";

export type ResultEncoding =
  | "json"
  | "decimal_string"
  | "integer_string"
  | "iso_date"
  | "iso_timestamp";

export type ResultValue = string | number | boolean | null;

export type ResultColumn = {
  name: string;
  logical_type: ResultLogicalType;
  database_type: string;
  encoding: ResultEncoding;
};

export type ResultCheck = {
  name: string;
  status: "passed" | "not_checked";
};

export type TableResult = {
  columns: ResultColumn[];
  rows: ResultValue[][];
  returned_rows: number;
  requested_limit: number;
  truncated: boolean;
  warnings: string[];
  checks: ResultCheck[];
};

export type ExecutionMetadata = {
  execution_id: string;
  dataset_version_id: string;
  dataset_sha256: string | null;
  plan_sha256: string | null;
  plan_version: number | null;
  compiler_version: string;
  executor_version: string;
  sqlglot_version: string;
  engine: "duckdb";
  engine_version: string;
  started_at: string;
  duration_ms: number;
  executed_sql: string | null;
};

export type ExecutionSuccess = {
  result_version: 1;
  status: "succeeded";
  table: TableResult;
  metadata: ExecutionMetadata;
};

export type ExecutionFailure = {
  result_version: 1;
  status: "failed";
  error: { code: string; message: string };
  metadata: ExecutionMetadata;
};

export type ExecutionResult = ExecutionSuccess | ExecutionFailure;

export type ChartSpec = {
  spec_version: 1;
  type: "bar" | "line";
  x: string;
  series: { column: string; label: string }[];
  missing_periods: "none" | "zero";
};

export type StoredAnalysisResult = {
  artifact_version: 1;
  execution: ExecutionSuccess;
  chart: ChartSpec | null;
};

export type AnalysisRunSummary = {
  id: string;
  status: "QUEUED" | "PROCESSING" | "NEEDS_CLARIFICATION" | "SUCCEEDED" | "FAILED";
  processing_stage: string;
  attempt_count: number;
  heartbeat_at: string | null;
  next_attempt_at: string | null;
  plan_sha256: string | null;
  result_sha256: string | null;
  error_code: string | null;
  error_message: string | null;
  validation_diagnostics: Array<Record<string, unknown>> | null;
  clarification_question: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};
