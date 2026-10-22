// Display text for the page: pure functions from contract values to Spanish strings.
import type {
  Booking,
  CandidateRecord,
  SourcesShown,
  StateUpdated,
  TurnFinished,
  VersionStamp,
} from "../api/contracts";

type Field = CandidateRecord[keyof Omit<CandidateRecord, "revision" | "notes">];

export const FIELDS: readonly (readonly [keyof CandidateRecord, string])[] = [
  ["name", "Nombre"],
  ["interest", "Interés"],
  ["work_authorization", "Permiso de trabajo"],
  ["availability_days", "Días"],
  ["availability_shifts", "Turnos"],
  ["hours_per_week", "Horas/semana"],
  ["earliest_start_date", "Inicio"],
  ["experience", "Experiencia"],
  ["contact_phone", "Teléfono"],
];

const STATUS_TEXT: Record<string, string> = {
  unknown: "no lo sabe",
  declined: "no quiere decirlo",
  unset: "—",
};

const CONFIRMATION_TEXT: Record<string, string> = {
  pending: "pendiente",
  confirmed: "confirmada",
  rejected: "rechazada",
  invalidated: "invalidada",
  expired: "caducada",
};

export const TERMINAL: ReadonlySet<StateUpdated["lifecycle"]> = new Set([
  "completed",
  "stopped",
  "abandoned",
  "failed",
]);

export function fieldText(field: Field | undefined): string {
  if (!field) return "—";
  if (field.status === "captured" || field.status === "confirmed") {
    const value = Array.isArray(field.value) ? field.value.join(", ") : String(field.value);
    return field.status === "confirmed" ? `${value} ✓` : value;
  }
  return STATUS_TEXT[field.status] ?? field.status;
}

export type Row = readonly [label: string, value: string];

export function candidateRows(update: StateUpdated | null): Row[] {
  const candidate = update?.candidate;
  const rows: Row[] = FIELDS.map(([key, label]) => [
    label,
    fieldText(candidate?.[key] as Field | undefined),
  ]);
  rows.push(["Notas", candidate?.notes.length ? candidate.notes.join(" · ") : "—"]);
  rows.push(["Revisión", String(update?.revision ?? 0)]);
  rows.push([
    "Estado",
    update ? `${update.lifecycle}${update.outcome ? ` · ${update.outcome}` : ""}` : "active",
  ]);
  return rows;
}

export function confirmationText(update: StateUpdated | null): string {
  const confirmation = update?.pending_confirmation;
  if (!confirmation) return "—";
  const label = CONFIRMATION_TEXT[confirmation.status] ?? confirmation.status;
  const revision = "revision" in confirmation.target ? confirmation.target.revision : "–";
  return `${label} (rev. ${revision}): ${confirmation.presentation_text}`;
}

export function bookingText(booking: Booking): string {
  const when = new Date(booking.starts_at_utc).toLocaleString("es-ES", {
    timeZone: "Europe/Madrid",
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${when} (hora de Madrid) · ${booking.slot_id}`;
}

export function versionRows(versions: VersionStamp): Row[] {
  return [
    ["Configuración", `${versions.config_id} v${versions.config_version}`],
    ["Modelo", versions.model_id],
    ["Prompt", versions.prompt_version],
    ["Conocimiento", versions.kb_version],
    ["Esquema", versions.schema_version],
    ["Commit", versions.commit_sha],
    ...(versions.stt_model ? [["Voz → texto", versions.stt_model] as const] : []),
    ...(versions.tts_model
      ? [["Texto → voz", `${versions.tts_model} · ${versions.voice_id}`] as const]
      : []),
  ];
}

// Title › section and an excerpt per chunk, as text.
export function sourceItems(sources: SourcesShown): { head: string; excerpt: string }[] {
  return sources.chunk_ids.map((_, i) => ({
    head: `${sources.titles[i].split(" / ")[0]} › ${sources.sections[i]}`,
    excerpt: sources.excerpts[i],
  }));
}

export function sourceLines(sources: SourcesShown): string[] {
  return [
    `búsqueda «${sources.question}»: ${sources.chunk_ids.length} fragmentos`,
    ...sources.chunk_ids.map(
      (_, i) => `  ${sources.titles[i]} › ${sources.sections[i]}: ${sources.excerpts[i]}`,
    ),
  ];
}

// The summary suffix and the two lines a finished turn adds to its reviewer entry.
export function finishedTurn(payload: TurnFinished): { detail: string; lines: string[] } {
  const ms = Object.fromEntries(payload.timings.map((t) => [t.stage, t.milliseconds]));
  const tokens = payload.usage
    .filter((u) => u.kind === "llm_tokens")
    .reduce((sum, u) => sum + u.quantity, 0);
  const timings = payload.timings
    .map((t) => `${t.stage}${t.tool_name ? `:${t.tool_name}` : ""} ${t.milliseconds} ms`)
    .join(", ");
  const usage = payload.usage
    .map((u) => `${u.kind} ${u.unit_detail} ${u.quantity}${u.estimated ? " (estimado)" : ""}`)
    .join(", ");
  return {
    detail: `${ms.llm_total ?? "–"} ms · ${tokens} tokens`,
    lines: [
      `tiempos: ${timings || "–"}`,
      `uso: ${usage || "–"}${payload.interrupted ? " · interrumpido" : ""}`,
    ],
  };
}
