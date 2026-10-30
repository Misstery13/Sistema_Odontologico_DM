import { useEffect, useState } from "react";
import { api, apiBlob, apiUpload, fmtDateTime } from "../api.js";

const KINDS = { radiografia: "Radiografía", foto: "Foto clínica", documento: "Documento" };
const kb = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`);

// miniatura: la imagen se pide autenticada y se muestra como blob (se registra como consulta en la auditoría)
function Preview({ a, onOpen }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!a.content_type.startsWith("image/")) return;
    let u;
    apiBlob(`/api/attachments/${a.id}/content/`).then((b) => setUrl((u = URL.createObjectURL(b))));
    return () => u && URL.revokeObjectURL(u);
  }, [a.id]);
  return (
    <button onClick={onOpen} className="flex h-40 w-full items-center justify-center overflow-hidden bg-desk hover:opacity-90" aria-label={`Abrir ${a.original_name}`}>
      {a.content_type.startsWith("image/")
        ? url ? <img src={url} alt={a.description || a.original_name} className="h-full w-full object-contain" /> : <span className="text-sm text-pencil">Cargando…</span>
        : <span className="text-3xl font-bold tracking-widest text-red">PDF</span>}
    </button>
  );
}

// alcance 2.3: radiografías, fotos y documentos planos en el expediente (sin visor DICOM)
export default function Attachments({ patient }) {
  const [items, setItems] = useState(null);
  const [kind, setKind] = useState("todos");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => api(`/api/attachments/?patient=${patient.id}`).then(setItems);
  useEffect(() => {
    load();
  }, [patient.id]);

  const upload = async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    data.append("patient", patient.id);
    setError("");
    setBusy(true);
    try {
      await apiUpload("/api/attachments/", data);
      form.reset();
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const open = async (a, download = false) => {
    const blob = await apiBlob(`/api/attachments/${a.id}/content/${download ? "?descargar=1" : ""}`);
    const url = URL.createObjectURL(blob);
    if (download) {
      const link = Object.assign(document.createElement("a"), { href: url, download: a.original_name });
      link.click();
    } else {
      window.open(url, "_blank", "noopener");
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };
  const shown = items?.filter((a) => kind === "todos" || a.kind === kind) ?? [];

  return (
    <section className="sheet">
      <div className="flex flex-wrap items-center gap-3 border-b-2 border-print px-5 py-4">
        <h2 className="text-xl font-semibold">Archivos del expediente</h2>
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="field ml-auto w-48" aria-label="Filtrar por tipo">
          <option value="todos">Todos los tipos</option>
          {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <form onSubmit={upload} className="grid gap-x-4 gap-y-3 border-b border-rule px-5 py-4 sm:grid-cols-[1fr_180px_1fr_auto]">
        <label><span className="label">Archivo (JPG, PNG o PDF, máx. 15 MB)</span>
          <input name="file" type="file" accept="image/jpeg,image/png,application/pdf" required className="mt-1 block w-full text-sm file:mr-3 file:rounded-[3px] file:border-0 file:bg-rule file:px-3 file:py-1.5 file:text-pen" />
        </label>
        <label><span className="label">Tipo</span>
          <select name="kind" className="field">{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </label>
        <label><span className="label">Descripción</span><input name="description" className="field" placeholder="Periapical pieza 36, panorámica…" /></label>
        <button className="btn self-end" disabled={busy}>{busy ? "Subiendo…" : "Subir"}</button>
        {error && <p className="error sm:col-span-4" role="alert">{error}</p>}
      </form>
      <ul className="grid gap-4 px-5 py-5 sm:grid-cols-2 lg:grid-cols-4">
        {shown.map((a) => (
          <li key={a.id} className="border border-rule">
            <Preview a={a} onOpen={() => open(a)} />
            <div className="space-y-0.5 px-3 py-2 text-sm">
              <p className="font-medium text-pen">{a.description || a.original_name}</p>
              <p className="text-pencil">{KINDS[a.kind]} · {kb(a.size)} · {fmtDateTime(a.created_at)}</p>
              <p className="text-pencil">{a.uploaded_by_name}</p>
              <button onClick={() => open(a, true)} className="link">Descargar</button>
            </div>
          </li>
        ))}
      </ul>
      {items?.length === 0 && <p className="px-5 pb-6 text-pencil">Sin archivos en el expediente.</p>}
    </section>
  );
}
