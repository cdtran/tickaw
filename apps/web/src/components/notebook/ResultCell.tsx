import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  ExecutionResult,
  ExecutionSuccess,
  AnalysisRunSummary,
  ChartSpec,
  ResultColumn,
  ResultValue,
  StoredAnalysisResult,
} from "../../types/api";

const CHART_ROW_LIMIT = 60;
const COLORS = ["#2358bd", "#0b7a63", "#b4541b", "#7b4bb7"];

type ChartModel = {
  kind: "bar" | "line";
  xColumn: ResultColumn;
  metricColumns: ResultColumn[];
  data: Record<string, string | number>[];
};

function displayValue(value: ResultValue, column: ResultColumn): string {
  if (value === null) return "Null";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (column.logical_type === "integer" || column.logical_type === "number") {
    if (column.encoding === "decimal_string" || column.encoding === "integer_string") {
      return String(value);
    }
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 8 }).format(Number(value));
  }
  if (column.logical_type === "timestamp" || column.logical_type === "timestamp_tz") {
    const parsed = new Date(String(value));
    if (!Number.isNaN(parsed.valueOf())) return parsed.toLocaleString();
  }
  return String(value);
}

function chartNumber(value: ResultValue): number | null {
  if (value === null || typeof value === "boolean") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function buildChart(result: ExecutionSuccess, spec?: ChartSpec | null): ChartModel | null {
  const { columns, rows } = result.table;
  if (!rows.length || rows.length > CHART_ROW_LIMIT) return null;

  if (spec) {
    const xColumn = columns.find((column) => column.name === spec.x);
    const metricColumns = spec.series
      .map((series) => columns.find((column) => column.name === series.column))
      .filter((column): column is ResultColumn => Boolean(column));
    if (!xColumn || metricColumns.length !== spec.series.length) return null;
    const xIndex = columns.indexOf(xColumn);
    const data = rows.map((row) => {
      const point: Record<string, string | number> = {
        [xColumn.name]: displayValue(row[xIndex], xColumn),
      };
      metricColumns.forEach((column) => {
        const value = chartNumber(row[columns.indexOf(column)]);
        if (value !== null) point[column.name] = value;
      });
      return point;
    });
    return { kind: spec.type, xColumn, metricColumns, data };
  }

  const metricIndexes = columns
    .map((column, index) => ({ column, index }))
    .filter(
      ({ column }) =>
        (column.logical_type === "integer" || column.logical_type === "number") &&
        column.encoding !== "integer_string",
    );
  const dimensionIndexes = columns
    .map((column, index) => ({ column, index }))
    .filter(({ index }) => !metricIndexes.some((metric) => metric.index === index));

  if (dimensionIndexes.length !== 1 || metricIndexes.length < 1 || metricIndexes.length > 4) {
    return null;
  }

  const dimension = dimensionIndexes[0];
  const supportedDimension = ["text", "boolean", "date", "timestamp", "timestamp_tz"].includes(
    dimension.column.logical_type,
  );
  if (!supportedDimension) return null;

  const data = rows.map((row) => {
    const point: Record<string, string | number> = {
      [dimension.column.name]: displayValue(row[dimension.index], dimension.column),
    };
    metricIndexes.forEach(({ column, index }) => {
      const value = chartNumber(row[index]);
      if (value !== null) point[column.name] = value;
    });
    return point;
  });

  return {
    kind: ["date", "timestamp", "timestamp_tz"].includes(dimension.column.logical_type)
      ? "line"
      : "bar",
    xColumn: dimension.column,
    metricColumns: metricIndexes.map(({ column }) => column),
    data,
  };
}

function ResultChart({ model }: { model: ChartModel }) {
  const common = {
    data: model.data,
    margin: { top: 12, right: 18, left: 0, bottom: 16 },
  };
  return (
    <div
      className="result-chart"
      role="img"
      aria-label={`${model.kind === "line" ? "Line" : "Bar"} chart of ${model.metricColumns
        .map((column) => column.name)
        .join(", ")} by ${model.xColumn.name}. Exact values are available in the results table.`}
    >
      <ResponsiveContainer width="100%" height="100%">
        {model.kind === "line" ? (
          <LineChart {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#dce4ee" />
            <XAxis dataKey={model.xColumn.name} tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} width={64} />
            <Tooltip />
            <Legend />
            {model.metricColumns.map((column, index) => (
              <Line
                key={column.name}
                type="monotone"
                dataKey={column.name}
                stroke={COLORS[index]}
                strokeWidth={2}
                connectNulls={false}
              />
            ))}
          </LineChart>
        ) : (
          <BarChart {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#dce4ee" />
            <XAxis dataKey={model.xColumn.name} tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} width={64} />
            <Tooltip />
            <Legend />
            {model.metricColumns.map((column, index) => (
              <Bar key={column.name} dataKey={column.name} fill={COLORS[index]} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

function ResultTable({ result, id }: { result: ExecutionSuccess; id: string }) {
  return (
    <div className="table-wrap">
      <table aria-describedby={id}>
        <thead>
          <tr>
            {result.table.columns.map((column) => (
              <th scope="col" key={column.name}>{column.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {result.table.columns.map((column, columnIndex) => (
                <td
                  key={column.name}
                  className={row[columnIndex] === null ? "null-value" : undefined}
                >
                  {displayValue(row[columnIndex], column)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ResultCell({
  result,
  chartSpec,
}: {
  result: ExecutionResult;
  chartSpec?: ChartSpec | null;
}) {
  const [mobileView, setMobileView] = useState<"chart" | "table">("chart");
  const descriptionId = useId();

  if (result.status === "failed") {
    return (
      <section className="analysis-result analysis-result-error" aria-label="Analysis failed">
        <h4>Couldn’t complete this analysis</h4>
        <p className="error">{result.error.message}</p>
        <p className="hint">Error code: {result.error.code}</p>
      </section>
    );
  }

  const chart = buildChart(result, chartSpec);
  const rowLabel = `${result.table.returned_rows} ${result.table.returned_rows === 1 ? "row" : "rows"}`;
  return (
    <section className="analysis-result" aria-label="Analysis result">
      <div className="result-heading">
        <div>
          <p className="result-kicker">Answer</p>
          <h4>Results</h4>
        </div>
        <span className="result-row-count">{rowLabel}</span>
      </div>

      {chart && (
        <div className="result-view-toggle" role="group" aria-label="Result view">
          <button
            type="button"
            className={mobileView === "chart" ? "active" : ""}
            aria-pressed={mobileView === "chart"}
            onClick={() => setMobileView("chart")}
          >
            Chart
          </button>
          <button
            type="button"
            className={mobileView === "table" ? "active" : ""}
            aria-pressed={mobileView === "table"}
            onClick={() => setMobileView("table")}
          >
            Table
          </button>
        </div>
      )}

      {chart && (
        <details className={`result-section result-chart-section mobile-view-${mobileView}`} open>
          <summary>Chart</summary>
          <ResultChart model={chart} />
        </details>
      )}

      <details className={`result-section result-table-section mobile-view-${mobileView}`} open>
        <summary>Table · {rowLabel}</summary>
        <p id={descriptionId} className="hint">
          Exact query values{result.table.truncated ? ` · limited to ${result.table.requested_limit} rows` : ""}.
        </p>
        {result.table.rows.length ? (
          <ResultTable result={result} id={descriptionId} />
        ) : (
          <p className="empty result-empty">The query returned no rows.</p>
        )}
        {result.table.truncated && (
          <p className="result-warning">More rows matched. Refine the question to narrow the result.</p>
        )}
      </details>

      <details className="result-provenance">
        <summary>How calculated</summary>
        <dl>
          <div><dt>Dataset version</dt><dd>{result.metadata.dataset_version_id}</dd></div>
          <div><dt>Plan fingerprint</dt><dd>{result.metadata.plan_sha256 ?? "Unavailable"}</dd></div>
          <div><dt>Engine</dt><dd>DuckDB {result.metadata.engine_version}</dd></div>
          <div><dt>Duration</dt><dd>{result.metadata.duration_ms} ms</dd></div>
        </dl>
        <p className="hint">
          Runtime checks passed for structure and execution. Question meaning is evaluated separately.
        </p>
      </details>
    </section>
  );
}

function elapsedLabel(start: string, end: string | null, now: number): string {
  const seconds = Math.max(0, Math.floor(((end ? Date.parse(end) : now) - Date.parse(start)) / 1000));
  if (seconds < 60) return `${seconds}s elapsed`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s elapsed`;
}

export function PersistedResult({
  analysis,
  notebookId,
  cellId,
  onRetried,
}: {
  analysis: AnalysisRunSummary;
  notebookId: string;
  cellId: string;
  onRetried: (run: AnalysisRunSummary) => void;
}) {
  const [run, setRun] = useState(analysis);
  const [artifact, setArtifact] = useState<StoredAnalysisResult | null>(null);
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (["SUCCEEDED", "FAILED", "NEEDS_CLARIFICATION"].includes(run.status)) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [run.status]);

  useEffect(() => {
    let active = true;
    setRun(analysis);
    setArtifact(null);
    setError("");
    setRetrying(false);
    setSubmitting(false);

    async function load() {
      if (!active) return;
      try {
        const statusResponse = await fetch(
          `/api/v1/analysis-runs/${encodeURIComponent(analysis.id)}`,
        );
        const statusBody = await statusResponse.json();
        if (!statusResponse.ok) {
          throw new Error(statusBody.detail ?? "Could not load analysis status.");
        }
        if (!active) return;
        const current = statusBody as AnalysisRunSummary;
        setRun(current);
        if (current.status === "SUCCEEDED") {
          const resultResponse = await fetch(
            `/api/v1/analysis-runs/${encodeURIComponent(analysis.id)}/result`,
          );
          const resultBody = await resultResponse.json();
          if (!resultResponse.ok) {
            throw new Error(resultBody.detail ?? "Could not load the saved result.");
          }
          if (active) setArtifact(resultBody as StoredAnalysisResult);
          return;
        }
        if (!["FAILED", "NEEDS_CLARIFICATION"].includes(current.status) && active) {
          window.setTimeout(load, 1000);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load analysis.");
      }
    }

    void load();
    return () => { active = false; };
  }, [analysis.id]);

  async function submitClarification(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch(
        `/api/v1/analysis-runs/${encodeURIComponent(run.id)}/clarification`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answer }),
        },
      );
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not submit clarification.");
      setRun(body as AnalysisRunSummary);
      setAnswer("");
      window.location.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not submit clarification.");
      setSubmitting(false);
    }
  }

  async function retry() {
    setRetrying(true);
    setError("");
    try {
      const response = await fetch(
        `/api/v1/notebooks/${encodeURIComponent(notebookId)}/cells/${encodeURIComponent(cellId)}/analysis-runs`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      );
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not retry this analysis.");
      onRetried(body as AnalysisRunSummary);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retry this analysis.");
      setRetrying(false);
    }
  }

  if (run.status === "NEEDS_CLARIFICATION") {
    return <section className="result-cell clarification" aria-labelledby={`clarify-${run.id}`}>
      <h3 id={`clarify-${run.id}`}>More information needed</h3>
      <p>{run.clarification_question ?? run.error_message ?? "Please clarify your question."}</p>
      <form onSubmit={submitClarification}>
        <label htmlFor={`clarification-${run.id}`}>Your answer</label>
        <textarea
          id={`clarification-${run.id}`}
          value={answer}
          maxLength={4000}
          required
          onChange={event => setAnswer(event.target.value)}
        />
        <button disabled={submitting || !answer.trim()} type="submit">
          {submitting ? "Resuming…" : "Resume analysis"}
        </button>
      </form>
      {error && <p role="alert" className="error">{error}</p>}
    </section>;
  }

  if (run.status === "FAILED") {
    return <><ResultCell result={{
      result_version: 1,
      status: "failed",
      error: {
        code: run.error_code ?? "ANALYSIS_FAILED",
        message: run.error_message ?? "The analysis could not be completed.",
      },
      metadata: {
        execution_id: run.id,
        dataset_version_id: "",
        dataset_sha256: null,
        plan_sha256: run.plan_sha256,
        plan_version: null,
        compiler_version: "",
        executor_version: "",
        sqlglot_version: "",
        engine: "duckdb",
        engine_version: "",
        started_at: run.created_at,
        duration_ms: 0,
        executed_sql: null,
      },
    }} />
      <button type="button" disabled={retrying} onClick={retry}>
        {retrying ? "Retrying…" : "Retry analysis"}
      </button>
      {error && <p role="alert" className="error">{error}</p>}
    </>;
  }
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!artifact) {
    const stages: Record<string, string> = {
      QUEUED: "Queued",
      RETRY_WAIT: "Waiting to retry",
      GENERATING_PLAN: "Generating query plan",
      DOWNLOADING_DATA: "Loading dataset",
      EXECUTING: "Running analysis",
    };
    const stage = stages[run.processing_stage]
      ?? run.processing_stage.toLowerCase().replaceAll("_", " ");
    const elapsed = elapsedLabel(run.started_at ?? run.created_at, run.completed_at, now);
    const attempt = run.attempt_count ? ` · attempt ${run.attempt_count} of 3` : "";
    const retryIn = run.next_attempt_at
      ? ` · retrying in ${Math.max(0, Math.ceil((Date.parse(run.next_attempt_at) - now) / 1000))}s`
      : "";
    return <p role="status" className="hint">{stage} · {elapsed}{attempt}{retryIn}</p>;
  }
  return <ResultCell result={artifact.execution} chartSpec={artifact.chart} />;
}
