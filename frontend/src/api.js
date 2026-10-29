export const getSession = () => JSON.parse(localStorage.getItem("session") || "null");

// fetch con token; lanza Error con el mensaje del backend (Django o Go)
export async function api(path, { method = "GET", body } = {}) {
  const token = getSession()?.token;
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...(token && { Authorization: `Token ${token}` }) },
    body: body && JSON.stringify(body),
  });
  if (res.status === 401 && token) {
    localStorage.removeItem("session");
    sessionStorage.setItem("logoutReason", "Tu sesión expiró. Ingresa de nuevo.");
    location.href = "/login";
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorText(data));
  return data;
}

function errorText(data) {
  if (!data) return "Error del servidor";
  if (data.detail) return data.detail;
  return Object.entries(data)
    .map(([k, v]) => (k === "non_field_errors" ? [].concat(v).join(" ") : `${k}: ${[].concat(v).join(" ")}`))
    .join(" · ");
}

export const money = (n) => Number(n).toLocaleString("es-EC", { style: "currency", currency: "USD" });

// devuelve un handler de submit que lee el form, llama a fn y muestra errores
export const formSubmit = (fn, setError) => async (e) => {
  e.preventDefault();
  setError("");
  const form = e.currentTarget;
  try {
    await fn(Object.fromEntries(new FormData(form)));
    form.reset();
  } catch (err) {
    setError(err.message);
  }
};

// la autorización real vive en el backend; esto solo decide qué controles mostrar
export const is = (...roles) => roles.includes(getSession()?.role);
export const STAFF = ["recepcion", "odontologo", "asistente"];

// imprime solo un documento (receta, consentimiento): el resto de la página queda oculto vía CSS @media print
export const printElement = (el) => {
  el.classList.add("print-doc");
  document.body.classList.add("printing");
  addEventListener("afterprint", () => { el.classList.remove("print-doc"); document.body.classList.remove("printing"); }, { once: true });
  print();
};

export const fmtDateTime = (s) => new Date(s).toLocaleString("es-EC", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
