import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import "./styles.css";

type Version = {
  id: string;
  version_number: number;
  status: string;
  original_filename: string;
  size_bytes: number | null;
  error_message: string | null;
};
type Dataset = { id: string; name: string; created_at: string; versions: Version[] };

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}

export default function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [target, setTarget] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [maximum, setMaximum] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [offset, setOffset] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  async function refresh(pageOffset = offset) {
    setLoading(true);
    try {
      const records = await readResponse<Dataset[]>(await fetch(`/api/v1/datasets?offset=${pageOffset}&limit=50`));
      setDatasets(records);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh(0).catch(() => setError("Could not load datasets. Check that the API is running, then refresh."));
    fetch("/api/v1/datasets/upload-config").then(readResponse<{ max_upload_bytes: number }>)
      .then(config => setMaximum(config.max_upload_bytes))
      .catch(() => setError("Could not load upload settings. Reload the page to try again."));
  }, []);

  async function upload(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!file || maximum === null) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setError("Choose a file ending in .csv."); return;
    }
    if (file.size === 0 || file.size > maximum) {
      setError(`Choose a nonempty CSV up to ${maximum / 1024 / 1024} MiB.`); return;
    }
    setBusy(true);
    let succeeded = false;
    try {
      const query = new URLSearchParams({ filename: file.name });
      if (target) query.set("dataset_id", target);
      const result = await readResponse<Dataset>(await fetch(`/api/v1/datasets/uploads?${query}`, {
        method: "POST",
        // Some browsers leave CSV's MIME type empty; use the standard CSV type then.
        headers: { "Content-Type": file.type || "text/csv" },
        body: file,
      }));
      succeeded = true;
      setNotice(`Uploaded ${file.name} to ${result.name}, version ${result.versions[0].version_number}.`);
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed. Refresh the list before retrying.");
    } finally {
      try {
        setOffset(0);
        setTarget("");
        await refresh(0);
      } catch {
        setError(succeeded ? "Upload succeeded, but the list could not refresh. Use Refresh to try again."
          : "Could not confirm the upload. Refresh the list before retrying.");
      }
      setBusy(false);
    }
  }

  async function navigate(nextOffset: number) {
    setError("");
    try {
      await refresh(nextOffset);
      setOffset(nextOffset);
      setTarget("");
    } catch { setError("Could not load datasets. Please try again."); }
  }

  return (
    <main>
      <header><p className="eyebrow">DATA NOTEBOOK</p><h1>Datasets</h1>
        <p>Upload a CSV and keep each version of your data.</p></header>
      <section className="upload-panel" aria-labelledby="upload-heading">
        <h2 id="upload-heading">Upload CSV</h2>
        <form onSubmit={upload}>
          <label htmlFor="dataset">Destination</label>
          <select id="dataset" value={target} onChange={event => setTarget(event.target.value)} disabled={busy || loading}>
            <option value="">Create a new dataset</option>
            {datasets.map(dataset => <option key={dataset.id} value={dataset.id}>New version of {dataset.name} ({dataset.id.slice(0, 8)})</option>)}
          </select>
          <label htmlFor="csv">CSV file</label>
          <input ref={input} id="csv" type="file" accept=".csv,text/csv" disabled={busy}
            onChange={event => { setFile(event.target.files?.[0] ?? null); setError(""); setNotice(""); }} />
          <p className="hint">UTF-8 CSV{maximum !== null ? ` · up to ${maximum / 1024 / 1024} MiB` : ""}. Originals are preserved; profiling and analysis come next.</p>
          <button type="submit" disabled={!file || busy || loading || maximum === null}>{busy ? "Uploading…" : "Upload CSV"}</button>
        </form>
      </section>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status" className="success">{notice}</p>}
      <section aria-labelledby="list-heading" aria-busy={loading}>
        <div className="section-heading"><h2 id="list-heading">Your datasets</h2>
          <button className="secondary" disabled={busy || loading} onClick={() => navigate(offset)}>Refresh</button></div>
        {loading && <p role="status">Loading datasets…</p>}
        {!loading && datasets.length === 0 && <p className="empty">{offset ? "No more datasets." : "No datasets yet. Upload your first CSV above."}</p>}
        {datasets.map(dataset => <article className="dataset" key={dataset.id}>
          <div className="section-heading"><h3>{dataset.name}</h3><span className="hint">{dataset.versions.length} version{dataset.versions.length === 1 ? "" : "s"}</span></div>
          <div className="table-wrap"><table><thead><tr><th>Version</th><th>Original file</th><th>Size</th><th>Status</th></tr></thead>
            <tbody>{dataset.versions.map(version => <tr key={version.id}>
              <td>v{version.version_number}</td><td>{version.original_filename}</td>
              <td>{version.size_bytes === null ? "—" : `${(version.size_bytes / 1024).toFixed(1)} KiB`}</td>
              <td><span className={`status ${version.status.toLowerCase()}`}>{version.status === "UPLOADED" ? "Uploaded · awaiting profiling" : version.status.replaceAll("_", " ").toLowerCase()}</span>
                {version.error_message && <p className="error">{version.error_message}</p>}</td>
            </tr>)}</tbody></table></div>
        </article>)}
        {(offset > 0 || datasets.length === 50) && <nav aria-label="Dataset pages">
          <button className="secondary" disabled={busy || loading || offset === 0} onClick={() => navigate(Math.max(0, offset - 50))}>Previous</button>
          <button className="secondary" disabled={busy || loading || datasets.length < 50} onClick={() => navigate(offset + 50)}>Next</button>
        </nav>}
      </section>
      <footer><a href="http://localhost:8000/docs">API documentation</a> · <a href="http://localhost:9001">Object storage console</a></footer>
    </main>
  );
}
