export type SelectableModel = {
  id: string;
  label: string;
  provider: string;
  description: string;
  requires_api_key: boolean;
};

export default function ModelSelector({ models, value, disabled, onChange }: {
  models: SelectableModel[];
  value: string;
  disabled?: boolean;
  onChange: (modelId: string) => void;
}) {
  const selected = models.find(model => model.id === value);
  return <div className="model-selector">
    <label htmlFor="question-model">Model</label>
    <select id="question-model" required value={value} disabled={disabled || !models.length}
      onChange={event => onChange(event.target.value)}>
      {!models.length && <option value="">No models available</option>}
      {models.map(model => <option key={model.id} value={model.id}>{model.label}</option>)}
    </select>
    {selected && <p className="hint">{selected.description}</p>}
  </div>;
}
