import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import ResultCell, { PersistedResult } from "../components/notebook/ResultCell";
import ModelSelector, { SelectableModel } from "../components/shared/ModelSelector";
import type { AnalysisRunSummary, ExecutionResult } from "../types/api";

type Notebook = { id: string; title: string };
type Cell = { id: string; question: string; dataset_version_id: string; stable_model_id: string; status: string; created_at: string; result?: ExecutionResult | null; latest_analysis?: AnalysisRunSummary | null };
type Detail = Notebook & { cells: Cell[] };
type Dataset = { id: string; name: string; versions: { id: string; version_number: number; status: string }[] };

async function request<T>(url: string, body?: object): Promise<T> {
  const response = await fetch(`/api/v1/${url}`, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  const text = await response.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* handled below */ }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please check your input and try again.");
  if (data === null) throw new Error("The server returned an unreadable response. Please try again.");
  return data as T;
}

async function allPages<T>(resource: string): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await request<T[]>(`${resource}?offset=${offset}&limit=100`);
    result.push(...page);
    if (page.length < 100) return result;
  }
}

export default function NotebookPage({ notebookId }: { notebookId: string }) {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [models, setModels] = useState<SelectableModel[]>([]);
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [version, setVersion] = useState("");
  const [modelId, setModelId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setDetail(null); setQuestion(""); setVersion("");
    Promise.all([allPages<Notebook>("notebooks"), allPages<Dataset>("datasets"), request<SelectableModel[]>("models"),
      notebookId ? request<Detail>(`notebooks/${encodeURIComponent(notebookId)}`) : Promise.resolve(null)])
      .then(([items, sources, availableModels, opened]) => { if (active) {
        setNotebooks(items); setDatasets(sources); setModels(availableModels); setDetail(opened);
        setModelId(current => current || availableModels[0]?.id || "");
      } })
      .catch(reason => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [notebookId]);
  const versions = datasets.flatMap(dataset => dataset.versions.map(item => ({ ...item,
    label: `${dataset.name} · v${item.version_number} · ${item.id.slice(0, 8)}` })));

  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const notebook = await request<Notebook>("notebooks", { title: title.trim() });
      setTitle(""); window.location.hash = `notebooks/${notebook.id}`;
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create notebook."); }
    finally { setBusy(false); }
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!detail) return;
    setBusy(true); setError("");
    try {
      const cell = await request<Cell>(`notebooks/${detail.id}/cells`, {
        question: question.trim(), dataset_version_id: version, stable_model_id: modelId,
      });
      setDetail(previous => previous ? { ...previous, cells: [...previous.cells, cell] } : previous);
      setQuestion("");
      try {
        const analysis = await request<AnalysisRunSummary>(
          `notebooks/${detail.id}/cells/${cell.id}/analysis-runs`,
          {},
        );
        setDetail(previous => previous ? {
          ...previous,
          cells: previous.cells.map(item => item.id === cell.id
            ? { ...item, latest_analysis: analysis }
            : item),
        } : previous);
      } catch (reason) {
        setError(`Question saved, but analysis could not be started: ${reason instanceof Error ? reason.message : "Please try again."}`);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save question."); }
    finally { setBusy(false); }
  }
  return <main>
    <nav><a href="#datasets">Datasets</a><a href="#notebooks">Notebooks</a></nav>
    <header><p className="eyebrow">tickaw</p><h1>{detail?.title ?? "Notebooks"}</h1>
      <p>Save questions against an exact version of your data.</p></header>
    {error && <p role="alert" className="error">{error}</p>}
    {loading ? <p role="status">Loading notebook…</p> : detail ? <>
      <section className="upload-panel"><h2>New question</h2>
        <p className="hint">The question is pinned to the selected dataset version and model before a plan is requested.</p>
        <form onSubmit={save}>
          <ModelSelector models={models} value={modelId} disabled={busy} onChange={setModelId} />
          <label htmlFor="question-version">Dataset version</label>
          <select id="question-version" required value={version} disabled={busy} onChange={event => setVersion(event.target.value)}>
            <option value="">Choose a profiled dataset version</option>
            {versions.filter(item => item.status === "READY").map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          {!versions.some(item => item.status === "READY") && <p>No ready datasets. <a href="#datasets">Upload and profile a CSV first.</a></p>}
          <label htmlFor="question">Question</label>
          <textarea id="question" rows={4} maxLength={4000} required value={question} disabled={busy}
            placeholder="Which region had the most revenue?" onChange={event => setQuestion(event.target.value)} />
          <button disabled={busy || !modelId || !version || !question.trim()}>{busy ? "Submitting…" : "Ask question"}</button>
        </form>
      </section>
      <section aria-label="Saved questions"><h2>Questions</h2>
        {!detail.cells.length && <p className="empty">No questions yet. Save your first question above.</p>}
        {detail.cells.map((cell, index) => <article className="dataset" key={cell.id}>
          <h3>Question {index + 1}</h3><p className="question-text">{cell.question}</p>
          <p className="hint">{versions.find(item => item.id === cell.dataset_version_id)?.label ?? cell.dataset_version_id}</p>
          <p className="hint">Model · {models.find(model => model.id === cell.stable_model_id)?.label ?? cell.stable_model_id}</p>
          <p className="hint">Saved · {new Date(cell.created_at).toLocaleString()}</p>
          {cell.result && <ResultCell result={cell.result} />}
          {!cell.result && cell.latest_analysis && <PersistedResult analysis={cell.latest_analysis} />}
        </article>)}
      </section>
    </> : !notebookId && <>
      <section className="upload-panel"><h2>Create notebook</h2><form onSubmit={create}>
        <label htmlFor="notebook-title">Title</label><input id="notebook-title" required maxLength={200} value={title}
          disabled={busy} onChange={event => setTitle(event.target.value)} placeholder="Sales analysis" />
        <button disabled={busy || !title.trim()}>{busy ? "Creating…" : "Create notebook"}</button>
      </form></section>
      <section><h2>Your notebooks</h2>{!notebooks.length && <p>No notebooks yet.</p>}
        {notebooks.map(item => <article className="dataset" key={item.id}><a href={`#notebooks/${item.id}`}>{item.title}</a></article>)}
      </section>
    </>}
  </main>;
}
