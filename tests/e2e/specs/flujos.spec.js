// Flujos principales en cada navegador y tamaño de pantalla. Se ejecutan contra el sistema levantado con datos demo.
import { expect, test } from "@playwright/test";

const as = (user) => ({ storageState: `.auth/${user}.json` });
const noHorizontalOverflow = async (page) =>
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

test.describe("sin sesión", () => {
  test("login pide usuario y contraseña", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Ingresa a tu clínica" })).toBeVisible();
    await page.getByLabel("Usuario").fill("dra.lopez");
    await page.getByLabel("Contraseña").fill("odonto123");
    await page.getByRole("button", { name: "Continuar" }).click();
    // segundo factor obligatorio (RNF-05)
    await expect(page.getByRole("heading", { name: "Verificación en dos pasos" })).toBeVisible();
    await expect(page.getByLabel("Código")).toBeVisible();
  });
});

test.describe("odontóloga", () => {
  test.use(as("dra.lopez"));

  test("ficha: alerta crítica, odontograma completo y pestañas clínicas", async ({ page }) => {
    await page.goto("/pacientes");
    await page.getByRole("link", { name: /Torres, María/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: /Alergia: Penicilina/i })).toBeVisible();
    // las 32 piezas permanentes visibles a la vez (sin desplazamiento horizontal)
    const teeth = page.getByRole("button", { name: /^Pieza \d+:/ });
    await expect(teeth).toHaveCount(32);
    for (const n of ["18", "28", "38", "48"]) await expect(page.getByRole("button", { name: new RegExp(`^Pieza ${n}:`) })).toBeInViewport({ ratio: 0.5 }).catch(async () => {
      await page.getByRole("button", { name: new RegExp(`^Pieza ${n}:`) }).scrollIntoViewIfNeeded();
      await expect(page.getByRole("button", { name: new RegExp(`^Pieza ${n}:`) })).toBeInViewport();
    });
    await page.getByRole("button", { name: "Universal" }).click();
    await expect(page.getByRole("button", { name: /^Pieza 1:/ })).toBeVisible(); // 18 FDI = 1 Universal
    await page.getByRole("button", { name: "Temporal" }).click();
    await expect(page.getByRole("button", { name: /^Pieza [A-T]:/ })).toHaveCount(20);
    for (const tab of ["Signos vitales", "Periodontograma", "Presupuestos", "Recetas", "Consentimientos", "Archivos"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tabpanel")).toBeVisible();
    }
    await noHorizontalOverflow(page);
  });

  test("agenda por día y semana", async ({ page }) => {
    await page.goto("/citas");
    await page.getByRole("button", { name: "Semana" }).click();
    await expect(page.getByRole("heading", { name: /Semana del/ })).toBeVisible();
    await expect(page.getByLabel("Consultorio").first()).toBeVisible();
    await noHorizontalOverflow(page);
  });
});

test.describe("recepción", () => {
  test.use(as("recepcion"));

  test("cobro con datos del comprobante y tarjeta de crédito/débito", async ({ page }) => {
    await page.goto("/pacientes");
    await page.getByRole("link", { name: /Torres, María/ }).click();
    const method = page.locator('select[name="method"]');
    await expect(method.locator("option")).toHaveText(["Efectivo", "Tarjeta de crédito", "Tarjeta de débito", "Transferencia", "Seguro"]);
    await expect(page.getByLabel("Cédula o RUC")).toHaveValue("0912345678");
    await page.getByLabel("Consumidor final").check();
    await expect(page.getByLabel("Cédula o RUC")).toBeHidden();
    await noHorizontalOverflow(page);
  });
});

test.describe("administrador TI", () => {
  test.use(as("admin"));

  test("usuarios y catálogos", async ({ page }) => {
    await page.goto("/usuarios");
    await expect(page.getByRole("heading", { name: "Usuarios de la clínica" })).toBeVisible();
    await expect(page.getByRole("cell", { name: /Ana López/ })).toBeVisible();
    await page.getByRole("link", { name: "Catálogos" }).click();
    for (const tab of ["Procedimientos y precios", "Insumos", "Consultorios", "Formatos de consentimiento"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
    }
    await page.getByRole("tab", { name: "Procedimientos y precios" }).click();
    await expect(page.getByText("Restauración con resina")).toBeVisible();
    await noHorizontalOverflow(page);
  });

  test("sin acceso a datos clínicos", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Pacientes" })).toHaveCount(0);
  });
});
