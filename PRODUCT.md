# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Recepción**: en el PC del mostrador, agenda citas, registra pacientes nuevos y cobra.
- **Odontólogo**: entre un paciente y otro, consulta la historia clínica, actualiza el odontograma y registra tratamientos.

Ambos trabajan con interrupciones constantes (teléfono, paciente esperando), así que cada tarea tiene que poder retomarse de un vistazo.

## Product Purpose

Odonto DM gestiona el día a día de una clínica dental: pacientes e historia clínica, agenda por odontólogo, odontograma y pagos contra el saldo de tratamientos. Funciona bien cuando recepción encuentra un hueco en la agenda o el saldo de un paciente en segundos, y el odontólogo ve las alergias y el estado de las piezas antes de atender.

## Positioning

Multitenant: varias clínicas comparten la plataforma y cada una ve solo sus datos. Los cobros nunca superan el saldo pendiente, incluso si se registran al mismo tiempo.

## Operating Context

- Proyecto académico (asignatura Framework Programación Web). Requisitos: SRS SIGO-Dental en `docs/`; implementada la Fase 1 + reglas de negocio (ver README).
- Moneda USD, zona horaria America/Guayaquil, idioma español (Ecuador).
- Numeración dental FDI (11–48).

## Capabilities and Constraints

- Pacientes: cédula única por clínica, alergias, antecedentes.
- Agenda: citas por odontólogo sin solapamiento; estados programada / completada / cancelada.
- Odontograma: estados sano, caries, obturado, endodoncia, corona, extraído.
- Tratamientos con costo; pagos (efectivo, tarjeta, transferencia) en un servicio Go aparte.
- Stack: React + Vite + Tailwind v4, Django REST, Go Fiber; servido por Caddy con CSP `default-src 'self'` (sin fuentes ni scripts externos salvo que se autoricen).
- Roles: administrador TI, recepción/caja, odontólogo, asistente dental, auditor (RBAC, menor privilegio).

## Brand Commitments

- Nombre del producto: **Odonto DM**.
- El nombre de cada clínica (tenant) aparece en la sesión.

## Evidence on Hand

Solo datos demo (`backend/clinica/management/commands/seed.py`). No hay logos, testimonios ni clientes reales; no inventarlos.

## Product Principles

1. Lo clínicamente crítico primero: alergias y saldo pendiente nunca quedan escondidos.
2. Una pantalla, una tarea: recepción no debe navegar tres niveles para agendar o cobrar.
3. Densidad sobre decoración: es una herramienta de trabajo diario.
4. Provisional por diseño: el alcance cambiará con los requisitos reales; no sobreconstruir.
