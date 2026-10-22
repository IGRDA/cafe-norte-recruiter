// A small line chart of probabilities over the candidate's messages (D62): one 0–1 axis, a
// labelled threshold, direct labels at the line ends, a native tooltip on every point and a
// table for screen readers. Colours are CSS classes (no inline style: the CSP, D38).

export interface Series {
  key: string; // the CSS class that colours it: .series-1 … .series-4
  label: string;
  values: number[]; // one per message, oldest first
}

interface Props {
  title: string;
  series: Series[];
  threshold: number; // the probability at which the runtime acts on it
}

const W = 320;
const H = 120;
const M = { top: 8, right: 74, bottom: 18, left: 26 };
const LABEL_GAP = 11; // px between stacked end labels
const percent = (p: number) => `${Math.round(p * 100)} %`;

/** End labels in value order, pushed apart so none overlap; each keeps a leader to its line. */
function placeLabels(ends: { key: string; y: number }[]): Map<string, number> {
  const sorted = [...ends].sort((a, b) => a.y - b.y);
  const placed: number[] = [];
  for (const end of sorted) {
    const previous = placed.at(-1);
    placed.push(previous === undefined ? end.y : Math.max(end.y, previous + LABEL_GAP));
  }
  const overflow = (placed.at(-1) ?? 0) - (H - M.bottom);
  return new Map(sorted.map((end, i) => [end.key, placed[i] - Math.max(0, overflow)]));
}

export function ProbabilityChart({ title, series, threshold }: Props) {
  const n = Math.max(0, ...series.map((s) => s.values.length));
  if (n === 0) return null;
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const x = (i: number) => M.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (p: number) => M.top + (1 - p) * plotH;
  const labels = placeLabels(series.map((s) => ({ key: s.key, y: y(s.values.at(-1) ?? 0) })));
  const lastX = x(n - 1);
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: probabilidad por mensaje, de 0 a 1`}>
        {[0, 0.5, 1].map((p) => (
          <g key={p} className="grid">
            <line x1={M.left} x2={M.left + plotW} y1={y(p)} y2={y(p)} />
            <text x={M.left - 4} y={y(p)} dy="0.32em" textAnchor="end">
              {p}
            </text>
          </g>
        ))}
        <g className="threshold">
          <line x1={M.left} x2={M.left + plotW} y1={y(threshold)} y2={y(threshold)} />
          <text x={M.left + 2} y={y(threshold)} dy="-0.35em">
            umbral {threshold}
          </text>
        </g>
        <text className="axis" x={M.left} y={H - 4}>
          1
        </text>
        {n > 1 && (
          <text className="axis" x={lastX} y={H - 4} textAnchor="end">
            {`mensaje ${n}`}
          </text>
        )}
        {series.map((s) => {
          const end = s.values.at(-1) ?? 0;
          const labelY = labels.get(s.key) ?? y(end);
          return (
            <g key={s.key} className={`line ${s.key}`}>
              {s.values.length > 1 && (
                <polyline points={s.values.map((p, i) => `${x(i)},${y(p)}`).join(" ")} />
              )}
              {s.values.map((p, i) => (
                <g key={i}>
                  <circle className="dot" cx={x(i)} cy={y(p)} r={3} />
                  <circle className="hit" cx={x(i)} cy={y(p)} r={8}>
                    <title>{`Mensaje ${i + 1} · ${s.label}: ${percent(p)}`}</title>
                  </circle>
                </g>
              ))}
              <line className="leader" x1={lastX + 4} x2={M.left + plotW + 8} y1={y(end)} y2={labelY} />
              <text className="end-label" x={M.left + plotW + 10} y={labelY} dy="0.32em">
                {`${s.label} ${percent(end)}`}
              </text>
            </g>
          );
        })}
      </svg>
      <table className="visually-hidden">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Mensaje</th>
            {series.map((s) => (
              <th key={s.key} scope="col">
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: n }, (_, i) => (
            <tr key={i}>
              <th scope="row">{i + 1}</th>
              {series.map((s) => (
                <td key={s.key}>{s.values[i] === undefined ? "—" : percent(s.values[i])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
