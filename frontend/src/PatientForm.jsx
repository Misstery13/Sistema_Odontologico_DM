import { useState } from "react";
import { formSubmit } from "./api.js";

const isMinor = (birth) => {
  if (!birth) return false;
  const b = new Date(`${birth}T12:00`);
  const adult = new Date(b.getFullYear() + 18, b.getMonth(), b.getDate());
  return adult > new Date();
};

function Field({ name, label, type = "text", required, initial, span, ...rest }) {
  return (
    <div className={span ? "col-span-2" : ""}>
      <label className="label" htmlFor={name}>{label}{required && <span className="text-red"> *</span>}</label>
      <input id={name} name={name} type={type} className="field" required={required} defaultValue={initial?.[name] ?? ""} {...rest} />
    </div>
  );
}

const Section = ({ title, children }) => (
  <fieldset className="col-span-2 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-dashed border-pencil/50 pt-4">
    <legend className="label-red pr-2">{title}</legend>
    {children}
  </fieldset>
);

// alta y edición de la ficha única (RF-01) con anamnesis obligatoria (RF-02)
export default function PatientForm({ initial, onSave, submitLabel = "Guardar ficha", onCancel }) {
  const [error, setError] = useState("");
  const [birth, setBirth] = useState(initial?.birth_date || "");
  const minor = isMinor(birth);

  const submit = formSubmit(async (data) => {
    data.anticoagulated = data.anticoagulated === "on";
    data.coagulopathy = data.coagulopathy === "on";
    if (!data.birth_date) data.birth_date = null;
    await onSave(data);
  }, setError);

  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-x-4 gap-y-4 px-5 py-5">
      <Field name="cedula" label="Cédula" required initial={initial} span />
      <Field name="first_name" label="Nombres" required initial={initial} />
      <Field name="last_name" label="Apellidos" required initial={initial} />
      <Field name="birth_date" label="Nacimiento" type="date" initial={initial} onChange={(e) => setBirth(e.target.value)} />
      <Field name="phone" label="Teléfono" type="tel" initial={initial} />
      <Field name="email" label="Email" type="email" initial={initial} span />
      <Field name="insurance" label="Seguro o convenio" initial={initial} span placeholder="Particular" />

      <Section title="Contacto de emergencia">
        <Field name="emergency_contact_name" label="Nombre" initial={initial} />
        <Field name="emergency_contact_phone" label="Teléfono" type="tel" initial={initial} />
      </Section>

      {minor && (
        <Section title="Tutor legal (menor de edad)">
          <Field name="guardian_name" label="Nombre" required initial={initial} />
          <Field name="guardian_cedula" label="Cédula" initial={initial} />
        </Section>
      )}

      <Section title="Anamnesis">
        <Field name="allergies" label="Alergias a fármacos" required initial={initial} span placeholder="Ninguna" />
        <Field name="systemic_diseases" label="Enfermedades sistémicas" required initial={initial} span placeholder="Ninguna" />
        <Field name="surgical_history" label="Antecedentes quirúrgicos" initial={initial} span />
        <div className="col-span-2">
          <label className="label" htmlFor="medical_history">Otros antecedentes</label>
          <textarea id="medical_history" name="medical_history" rows="2" className="field resize-none" defaultValue={initial?.medical_history ?? ""} />
        </div>
        {[["anticoagulated", "Toma anticoagulantes"], ["coagulopathy", "Coagulopatía"]].map(([name, label]) => (
          <label key={name} className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" name={name} defaultChecked={initial?.[name]} className="h-4 w-4 accent-red" />
            {label}
          </label>
        ))}
      </Section>

      {error && <p className="error col-span-2" role="alert">{error}</p>}
      <div className="col-span-2 flex gap-3">
        <button className="btn flex-1">{submitLabel}</button>
        {onCancel && <button type="button" onClick={onCancel} className="link px-3">Cancelar</button>}
      </div>
    </form>
  );
}
