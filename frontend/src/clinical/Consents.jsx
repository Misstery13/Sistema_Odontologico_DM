import { useEffect, useRef, useState } from "react";
import { api, fmtDateTime, getSession, printElement } from "../api.js";

// firma manuscrita en pantalla táctil / mouse: canvas nativo, exporta PNG
function SignaturePad({ onChange }) {
  const ref = useRef(null);
  const drawing = useRef(false);
  const ink = useRef(0);

  useEffect(() => {
    const c = ref.current;
    const ratio = devicePixelRatio || 1;
    c.width = c.offsetWidth * ratio;
    c.height = c.offsetHeight * ratio;
    const ctx = c.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2.2;
    ctx.lineCap = ctx.lineJoin = "round";
    ctx.strokeStyle = getComputedStyle(c).getPropertyValue("--color-pen") || "#2342a8";
  }, []);

  const pos = (e) => {
    const r = ref.current.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const down = (e) => {
    drawing.current = true;
    ref.current.setPointerCapture(e.pointerId);
    const ctx = ref.current.getContext("2d");
    ctx.beginPath();
    ctx.moveTo(...pos(e));
  };
  const move = (e) => {
    if (!drawing.current) return;
    const ctx = ref.current.getContext("2d");
    ctx.lineTo(...pos(e));
    ctx.stroke();
    ink.current += 1;
  };
  const up = () => {
    if (!drawing.current) return;
    drawing.current = false;
    onChange(ink.current > 10 ? ref.current.toDataURL("image/png") : ""); // descarta toques accidentales
  };
  const clear = () => {
    const c = ref.current;
    c.getContext("2d").clearRect(0, 0, c.width, c.height);
    ink.current = 0;
    onChange("");
  };

  return (
    <div>
      <canvas ref={ref} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        aria-label="Área de firma" className="h-44 w-full touch-none rounded-[3px] border-2 border-dashed border-pen bg-white" />
      <div className="mt-1 flex justify-between text-sm">
        <span className="text-pencil">Firme dentro del recuadro</span>
        <button type="button" onClick={clear} className="link">Borrar firma</button>
      </div>
    </div>
  );
}

function ConsentDocument({ c, patient }) {
  const ref = useRef(null);
  return (
    <div className="mt-3">
      <div ref={ref} className="sheet border border-rule px-8 py-6">
        <div className="flex items-baseline justify-between border-b-4 border-red pb-2">
          <span className="text-sm font-bold uppercase tracking-[0.14em] text-red">{getSession().clinic}</span>
          <span className="label">Consentimiento informado · {c.procedure}</span>
        </div>
        <div className="mt-4 whitespace-pre-line leading-relaxed">{c.text}</div>
        {c.signed ? (
          <div className="mt-6 border-t border-print pt-3 text-sm">
            {c.method === "biometrica" && <img src={c.signature_image} alt={`Firma de ${c.signer_name}`} className="h-24" />}
            <p className="hand text-xl">{c.signer_name}</p>
            <p className="text-pencil">
              Firmado el {fmtDateTime(c.signed_at)} {c.method === "otp" ? `con código OTP enviado a ${patient.phone || patient.email}` : "en pantalla táctil"}
            </p>
            <p className="text-xs text-pencil">Firma digital {c.signature}</p>
          </div>
        ) : (
          <p className="mt-6 font-semibold text-red">Pendiente de firma</p>
        )}
      </div>
      <button onClick={() => api(`/api/consents/${c.id}/export/`).then(() => printElement(ref.current))} className="link mt-2">Imprimir</button>
    </div>
  );
}

function SignPanel({ c, patient, onSigned }) {
  const [method, setMethod] = useState("biometrica");
  const [signer, setSigner] = useState(patient.is_minor ? patient.guardian_name : `${patient.first_name} ${patient.last_name}`);
  const [image, setImage] = useState("");
  const [otp, setOtp] = useState(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  const run = async (fn) => {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    }
  };
  const requestOtp = () => run(async () => setOtp(await api(`/api/consents/${c.id}/request-otp/`, { method: "POST" })));
  const sign = (e) => {
    e.preventDefault();
    const body = method === "otp" ? { method, signer_name: signer, code } : { method, signer_name: signer, signature_image: image };
    run(async () => onSigned(await api(`/api/consents/${c.id}/sign/`, { method: "POST", body })));
  };
  const tab = (v, label) => (
    <button type="button" onClick={() => setMethod(v)} aria-pressed={method === v}
      className={`px-3 py-1 text-sm font-semibold ${method === v ? "bg-pen text-white" : "text-pen hover:bg-rule/50"}`}>{label}</button>
  );

  return (
    <form onSubmit={sign} className="mt-4 space-y-4 rounded-[3px] border border-rule p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h4 className="label-red">Firmar</h4>
        <div className="flex rounded-[3px] border border-pen" role="group">{tab("biometrica", "Firma en pantalla")}{tab("otp", "Código OTP")}</div>
      </div>
      <label className="block"><span className="label">Firma {patient.is_minor ? "(tutor legal)" : "(paciente)"}</span>
        <input className="field" value={signer} onChange={(e) => setSigner(e.target.value)} required />
      </label>
      {method === "biometrica" ? (
        <SignaturePad onChange={setImage} />
      ) : (
        <div className="flex flex-wrap items-end gap-4">
          <button type="button" onClick={requestOtp} className="link">{otp ? "Reenviar código" : "Enviar código al paciente"}</button>
          {otp && <span className="text-sm text-pencil">Enviado por {otp.channel} a {otp.sent_to}; vence en 10 minutos.</span>}
          {otp && (
            <label className="w-36"><span className="label">Código</span>
              <input className="field tracking-[0.3em]" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
            </label>
          )}
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <button className="btn" disabled={method === "biometrica" ? !image : code.length !== 6}>Registrar firma</button>
    </form>
  );
}

// RF-06: consentimiento por procedimiento, firmado una sola vez
export default function Consents({ patient }) {
  const [list, setList] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");
  const load = () => api(`/api/consents/?patient=${patient.id}`).then(setList);
  useEffect(() => {
    load();
    api("/api/consent-templates/").then((l) => setTemplates(l.filter((t) => t.active)));
  }, [patient.id]);

  const create = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const c = await api("/api/consents/", { method: "POST", body: { patient: patient.id, template: Number(new FormData(e.currentTarget).get("template")) } });
      setOpen(c.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  };
  const replace = (c) => setList(list.map((x) => (x.id === c.id ? c : x)));

  return (
    <section className="sheet">
      <div className="flex flex-wrap items-end gap-4 border-b-2 border-print px-5 py-4">
        <h2 className="text-xl font-semibold">Consentimientos informados</h2>
        <form onSubmit={create} className="ml-auto flex items-end gap-3">
          <label className="w-56"><span className="label">Procedimiento</span>
            <select name="template" className="field" required>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.procedure}</option>)}
            </select>
          </label>
          <button className="btn">Generar formato</button>
        </form>
      </div>
      {error && <p className="error px-5 pt-3" role="alert">{error}</p>}
      <ul className="px-5">
        {list?.map((c) => (
          <li key={c.id} className="rule-row py-3">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="font-semibold text-pen">{c.procedure}</span>
              <span className="text-sm text-pencil">{fmtDateTime(c.created_at)}</span>
              {c.signed
                ? <span className="text-sm text-pen">Firmado por {c.signer_name} · {c.method === "otp" ? "OTP" : "en pantalla"}</span>
                : <span className="text-sm font-semibold text-red">Pendiente de firma</span>}
              <button onClick={() => setOpen(open === c.id ? null : c.id)} className="link ml-auto">{open === c.id ? "Ocultar" : c.signed ? "Ver e imprimir" : "Revisar y firmar"}</button>
            </div>
            {open === c.id && (
              <>
                <ConsentDocument c={c} patient={patient} />
                {!c.signed && <SignPanel c={c} patient={patient} onSigned={replace} />}
              </>
            )}
          </li>
        ))}
        {list?.length === 0 && <li className="py-6 text-pencil">Sin consentimientos generados.</li>}
      </ul>
    </section>
  );
}
