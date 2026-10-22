import type { SignalPoint } from "../page/reducer";
import { ProbabilityChart } from "./ProbabilityChart";

// What the classifier read in the latest message (D62): tone and language probabilities, and
// how they moved over the conversation. Advisory and about the words, never about the person.
// Not a live region: it changes every message and must not talk over Ana.

const TONES = [
  ["neutral", "neutral"],
  ["positive", "positivo"],
  ["frustrated", "frustrado"],
  ["uncertain", "dudoso"],
] as const;

// Same thresholds as the runtime (conversation/signals.py): what it acts on.
const SENTIMENT_THRESHOLD = 0.5;
const SWITCH_THRESHOLD = 0.7;

interface Props {
  status: "off" | "idle" | "waiting" | "ready";
  latest: SignalPoint | null;
  series: NonNullable<SignalPoint["probabilities"]>[];
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

export function Signals({ status, latest, series }: Props) {
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
        <strong>Señales</strong> · probabilidades por mensaje
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
        </div>
      )}
      {status !== "off" && series.length > 0 && (
        <div className="charts">
          <ProbabilityChart
            title="Tono"
            threshold={SENTIMENT_THRESHOLD}
            series={TONES.map(([key, label], i) => ({
              key: `series-${i + 1}`,
              label,
              values: series.map((p) => p.sentiment[key] ?? 0),
            }))}
          />
          <ProbabilityChart
            title="Idioma"
            threshold={SWITCH_THRESHOLD}
            series={[{ key: "series-1", label: "cambiar", values: series.map((p) => p.language.switch ?? 0) }]}
          />
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
