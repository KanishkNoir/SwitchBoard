type Scalar = string | number | boolean;
export type ScopeDraft = { global: boolean; fields: { name: string; values: Scalar[] }[] };

export function scopeDraft(scope: { mandatory?: Record<string, unknown>; global?: boolean }): ScopeDraft {
  return { global: scope.global === true, fields: Object.entries(scope.mandatory ?? {}).map(([name, value]) => ({
    name, values: (Array.isArray(value) ? value : [value]).map((v) =>
      typeof v === "number" || typeof v === "boolean" || typeof v === "string" ? v : String(v)),
  })) };
}

export function scopeValue(draft: ScopeDraft) {
  if (draft.global) return { global: true };
  const mandatory: Record<string, Scalar | Scalar[]> = Object.create(null) as Record<string, Scalar | Scalar[]>;
  for (const field of draft.fields) {
    const key = field.name.trim();
    if (!key || key in mandatory || !field.values.length
      || field.values.some((v) => typeof v === "string" ? !v.trim() : typeof v === "number" && !Number.isFinite(v))) {
      throw new Error("Give each boundary a unique field name and at least one value.");
    }
    mandatory[key] = field.values.length === 1 ? field.values[0] : field.values;
  }
  if (!Object.keys(mandatory).length) throw new Error("Add a boundary before saving this rule.");
  return { mandatory };
}

export function ScopeEditor({ value, onChange, allowGlobal = false, required = [] }: {
  value: ScopeDraft; onChange: (value: ScopeDraft) => void; allowGlobal?: boolean; required?: string[];
}) {
  const update = (index: number, patch: Partial<ScopeDraft["fields"][number]>) =>
    onChange({ ...value, fields: value.fields.map((f, i) => i === index ? { ...f, ...patch } : f) });
  return <div className="scope-editor" role="group" aria-label="Rule boundaries" style={{ display: "grid", gap: 8 }}>
    {!!required.length && <div className="bb">Required boundaries: {required.join(", ")}</div>}
    {(allowGlobal || value.global) && <label className="bb">
      <input type="checkbox" checked={value.global}
        onChange={(e) => onChange({ ...value, global: e.target.checked })} />
      {" "}Apply everywhere in this category {allowGlobal ? "(deliberate global rule)" : "— global rules are no longer allowed"}
    </label>}
    {!value.global && value.fields.map((field, index) => <div className="detailbox" key={index} style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <input aria-label={`Boundary ${index + 1} field`} value={field.name} placeholder="Only when… field (e.g. project)"
          onChange={(e) => update(index, { name: e.target.value })} style={{ flex: 1, minWidth: 0 }} />
        <button type="button" onClick={() => onChange({ ...value, fields: value.fields.filter((_, i) => i !== index) })}>Remove boundary</button>
      </div>
      {field.values.map((entry, vi) => <div key={vi} style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <select aria-label={`Boundary ${index + 1} value ${vi + 1} type`} value={typeof entry}
          onChange={(e) => update(index, { values: field.values.map((v, i) => i !== vi ? v :
            e.target.value === "boolean" ? false : e.target.value === "number" ? 0 : "") })}>
          <option value="string">Text</option><option value="number">Number</option><option value="boolean">Yes / no</option>
        </select>
        {typeof entry === "boolean" ? <select aria-label={`Boundary ${index + 1} value ${vi + 1}`}
          value={String(entry)} onChange={(e) => update(index, { values: field.values.map((v, i) => i === vi ? e.target.value === "true" : v) })}>
          <option value="true">Yes</option><option value="false">No</option>
        </select> : <input aria-label={`Boundary ${index + 1} value ${vi + 1}`} type={typeof entry === "number" ? "number" : "text"}
          value={entry} placeholder="…equals" style={{ flex: 1, minWidth: 0 }}
          onChange={(e) => update(index, { values: field.values.map((v, i) => i === vi ?
            typeof entry === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value : v) })} />}
        {field.values.length > 1 && <button type="button" onClick={() => update(index, { values: field.values.filter((_, i) => i !== vi) })}>Remove value</button>}
      </div>)}
      <button type="button" onClick={() => update(index, { values: [...field.values, ""] })}>Add alternative value</button>
    </div>)}
    {!value.global && <button type="button" onClick={() => onChange({ ...value, fields: [...value.fields, { name: "", values: [""] }] })}>Add boundary</button>}
  </div>;
}
