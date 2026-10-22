import type { SignalPoint, SignalsMode } from "../page/reducer";

// What the classifier read in the latest message (D62): tone and language, with Jev's
// probabilities, and a short trend. Advisory and about the words, never about the person.
// Not a live region: it changes every message and must not talk over Ana.

const TONES = [
  ["neutral", "neutral"],
  ["positive", "positivo"],
  ["frustrated", "frustrado"],
  ["uncertain", "dudoso"],
] as const;

const SOURCE: Record<SignalsMode, string> = { off: "sin clasificador", labels: "solo etiquetas", jev: "Jev" };

interface Props {
  mode: SignalsMode;
  status: "off" | "idle" | "waiting" | "ready";
  latest: SignalPoint | null;
  frustrated: number[];
  switching: number[];
}

function percent(p: number): string {
  return `${Math.round(p * 100)} %`;
}

function Bar({ label, value, chosen }: { label: string; value: number; chosen: boolean }) {
  return (
    <div className={chosen ? "bar chosen" : "bar"}>
      <span>{label}</span>
      <meter min={0} max={1} value={value} aria-label={label} />
      <span className="value">{percent(value)}</span>
    </div>
  );
}

function Trend({ label, values }: { label: string; values: number[] }) {
  if (values.length < 2) return null;
  return (
    <div className="trend" role="img" aria-label={`${label}: ${values.map(percent).join(", ")}`}>
      <span>{label}</span>
      {values.map((value, i) => (
        <meter key={i} min={0} max={1} value={value} aria-hidden="true" />
      ))}
    </div>
  );
}

export function Signals({ mode, status, latest, frustrated, switching }: Props) {
  const note =
    status === "off"
      ? "Ningún clasificador lee los mensajes en esta demo."
      : status === "idle"
        ? "Aparecerán con tu primer mensaje."
        : status === "waiting"
          ? "Leyendo tu último mensaje…"
          : null;
  const probabilities = latest?.probabilities;
  return (
    <section className="signals" aria-label="Señales del último mensaje">
      <p className="signals-head">
        <strong>Señales</strong> · último mensaje · <span>{SOURCE[mode]}</span>
      </p>
      {note && <p className="notice">{note}</p>}
      {status !== "off" && latest && probabilities && (
        <div className="signals-body">
          <div className="group">
            <span className="group-label">Tono</span>
            {TONES.map(([key, label]) => (
              <Bar key={key} label={label} value={probabilities.sentiment[key] ?? 0} chosen={latest.sentiment === key} />
            ))}
          </div>
          <div className="group">
            <span className="group-label">Idioma</span>
            <Bar label="mantener" value={probabilities.language.keep ?? 0} chosen={!latest.switchTo} />
            <Bar label="cambiar" value={probabilities.language.switch ?? 0} chosen={latest.switchTo !== null} />
          </div>
          <Trend label="frustración" values={frustrated} />
          <Trend label="cambio de idioma" values={switching} />
        </div>
      )}
      {status !== "off" && latest && !probabilities && (
        <p className="notice">
          Tono: {TONES.find(([key]) => key === latest.sentiment)?.[1]}
          {latest.switchTo ? ` · pide cambiar a ${latest.switchTo}` : ""}
        </p>
      )}
    </section>
  );
}
