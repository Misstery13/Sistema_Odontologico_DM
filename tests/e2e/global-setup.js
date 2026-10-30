// Inicia sesión una vez por usuario (contraseña + TOTP del secreto demo) y guarda la sesión para todos los navegadores:
// cada código MFA sirve una sola vez, así que no se puede ingresar en paralelo desde cinco navegadores.
import { createHmac } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8080";
export const USERS = ["dra.lopez", "recepcion", "admin"];

const base32 = (s) => {
  const bits = [...s].map((c) => "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567".indexOf(c).toString(2).padStart(5, "0")).join("");
  return Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
};
const totp = (secret) => {
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = createHmac("sha1", base32(secret)).update(msg).digest();
  return String((h.readUInt32BE(h[h.length - 1] & 15) & 0x7fffffff) % 1e6).padStart(6, "0");
};
const post = async (path, body) => {
  const r = await fetch(BASE + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return [r.status, await r.json()];
};

export default async function globalSetup() {
  mkdirSync(".auth", { recursive: true });
  for (const user of USERS) {
    const [, step] = await post("/api/login/", { username: user, password: "odonto123" });
    let session;
    for (let i = 0; i < 2 && !session; i++) {
      const [status, s] = await post("/api/login/mfa/", { ticket: step.ticket, code: totp("ODONTODMDEMOMFA2") });
      if (status === 200) session = s;
      else await new Promise((r) => setTimeout(r, 31000 - (Date.now() % 30000))); // código ya usado: esperar al siguiente
    }
    if (!session) throw new Error(`No se pudo iniciar sesión como ${user}`);
    writeFileSync(`.auth/${user}.json`, JSON.stringify({
      cookies: [],
      origins: [{ origin: BASE, localStorage: [{ name: "session", value: JSON.stringify(session) }] }],
    }));
  }
}
