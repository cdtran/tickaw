import { apiFetch } from "./api/client";
import { useEffect, useRef, useState } from "react";

type Cell = string | number | boolean | null;
type Column = { name: string; inferred_type: string; pandas_dtype: string };
type ColumnProfile = { name: string; null_count: number; sample_values: Cell[] };
type Detail = {
  id: string; version_number: number; status: string; original_filename: string;
  row_count: number | null; error_code: string | null; error_message: string | null;
  schema_json: { columns: Column[] } | null;
  profile_json: { column_count: number; columns: ColumnProfile[]; null_policy: string; type_policy: string; display_character_limit: number } | null;
  preview_json: Record<string, Cell>[] | null;
  job: { status: string; attempt_count: number; error_message: string | null } | null;
};

function show(value: Cell) { return value === null ? "null" : String(value); }

export default function VersionProfile({ versionId, onStatus }: {
  versionId: string;
  onStatus: (id: string, status: string, error: string | null) => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [requesting, setRequesting] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const notify = useRef(onStatus);
  notify.current = onStatus;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setDetail(null);
    setError("");
    async function load() {
      try {
        const response = await apiFetch(`/api/v1/datasets/versions/${versionId}`, { signal: controller.signal });
        if (!response.ok) throw new Error("Could not load this version's profile.");
        const record: Detail = await response.json();
        if (controller.signal.aborted) return;
        setDetail(record);
        notify.current(record.id, record.status, record.error_message);
        if (record.job && ["QUEUED", "PROCESSING"].includes(record.job.status)) {
          timer = setTimeout(load, 2000);
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not load profile.");
      }
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [versionId, refresh]);

  async function start() {
    setRequesting(true);
    setError("");
    try {
      const response = await apiFetch(`/api/v1/datasets/versions/${versionId}/profile`, { method: "POST" });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(typeof body.detail === "string" ? body.detail : "Could not start profiling.");
      }
      setRefresh(value => value + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start profiling."); }
    finally { setRequesting(false); }
  }

  const current = detail?.id === versionId ? detail : null;
  const fileErrors = new Set(["INVALID_CSV", "INVALID_HEADER", "DUPLICATE_COLUMNS", "UNSUPPORTED_ENCODING",
    "UNSUPPORTED_FORMAT", "UNSUPPORTED_DELIMITER", "FIELD_LIMIT", "COLUMN_LIMIT", "ROW_LIMIT", "FILE_TOO_LARGE"]);
  const fileRejected = current?.error_code ? fileErrors.has(current.error_code) : false;
  return <section className="profile-panel" aria-label="Dataset version profile">
    {error && <p role="alert" className="error">{error} <button className="secondary" onClick={() => setRefresh(value => value + 1)}>Try loading again</button></p>}
    {!current && !error && <p role="status">Loading version…</p>}
    {current && <>
      <h3>Version {current.version_number} · {current.original_filename}</h3>
      {current.status !== "READY" && <>
        <p role="status">{current.job?.status === "QUEUED" ? "Queued for profiling…" : current.status === "PROCESSING" ? "Profiling CSV…" : current.status === "FAILED" ? (fileRejected ? "CSV could not be profiled." : "Processing failed.") : "This version has not been profiled yet."}</p>
        {current.job && <p className="hint">Attempt {current.job.attempt_count} of 3. {current.job.status === "QUEUED" && current.job.error_message ? "Storage is temporarily unavailable; retrying automatically." : ""}</p>}
        {current.status === "FAILED" && <div role="alert" className="error">
          <p>{current.error_message}</p>
          <p>{fileRejected ? "Correct the file and upload it as a new version of this dataset."
            : "Check the local storage and worker before uploading again; changing the CSV may not fix this error."}</p>
          <p className="hint">Error: {current.error_code ?? "UNKNOWN"}. No analysis-ready profile was published for this version.</p>
        </div>}
        {current.status === "UPLOADED" && !current.job && <button disabled={requesting} onClick={start}>{requesting ? "Requesting…" : "Profile CSV"}</button>}
      </>}
      {current.status === "READY" && current.schema_json && current.profile_json && <>
        <p><strong>{current.row_count?.toLocaleString()} rows</strong> · {current.profile_json.column_count} columns</p>
        <h4>Schema & samples</h4>
        <div className="table-wrap"><table><thead><tr><th>Column</th><th>Inferred type</th><th>Nulls</th><th>Sample values</th></tr></thead>
          <tbody>{current.schema_json.columns.map(column => {
            const profile = current.profile_json!.columns.find(item => item.name === column.name);
            return <tr key={column.name}><th scope="row">{column.name}</th><td>{column.inferred_type}</td>
              <td>{profile?.null_count.toLocaleString()}</td><td>{profile?.sample_values.length ? profile.sample_values.map(show).join(" · ") : "No non-null values"}</td></tr>;
          })}</tbody></table></div>
        <p className="hint">{current.profile_json.null_policy} {current.profile_json.type_policy}</p>
        <h4>Data preview · first {current.preview_json?.length ?? 0} rows</h4>
        {current.preview_json?.length ? <div className="table-wrap"><table><thead><tr>{current.schema_json.columns.map(column => <th key={column.name}>{column.name}</th>)}</tr></thead>
          <tbody>{current.preview_json.map((row, index) => <tr key={index}>{current.schema_json!.columns.map(column => <td key={column.name} className={row[column.name] === null ? "null-value" : ""}>{show(row[column.name])}</td>)}</tr>)}</tbody></table></div>
          : <p>This CSV has column headers but no data rows.</p>}
        <p className="hint">Long sample and preview values are shortened after {current.profile_json.display_character_limit} characters. The original and normalized data retain full values.</p>
      </>}
    </>}
  </section>;
}
