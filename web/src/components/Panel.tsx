import { bookingText, candidateRows, confirmationText, sourceItems, versionRows, type Row } from "../page/format";
import {
  canAnswer,
  canDelete,
  canEnd,
  confirmationOpen,
  exportHref,
  type Action,
  type ReviewEntry,
  type State,
} from "../page/reducer";

interface Props {
  state: State;
  dispatch: (action: Action) => void;
}

function Rows({ rows, className }: { rows: Row[]; className?: string }) {
  return (
    <dl className={className}>
      {rows.map(([label, value]) => (
        <div key={label} className="row">
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Panel({ state, dispatch }: Props) {
  const confirmation = state.candidate?.pending_confirmation;
  const booking = state.candidate?.booking;
  const href = exportHref(state);
  return (
    <aside className="panel">
      <h2>Ficha del candidato</h2>
      <Rows rows={candidateRows(state.candidate)} />
      <h2>Confirmación</h2>
      <p className="confirmation" data-status={confirmation?.status}>
        {confirmationText(state.candidate)}
      </p>
      {confirmationOpen(state) && (
        <p className="actions">
          <button type="button" disabled={!canAnswer(state)} onClick={() => dispatch({ type: "confirmation-answered", answer: "affirm" })}>
            Sí
          </button>
          <button type="button" disabled={!canAnswer(state)} onClick={() => dispatch({ type: "confirmation-answered", answer: "deny" })}>
            No
          </button>
        </p>
      )}
      {/* Only a committed reservation reaches the stream, so this never runs ahead of storage. */}
      {booking && (
        <section className="booking" aria-live="polite">
          <h2>Entrevista</h2>
          <p>{bookingText(booking)}</p>
          <p className="notice">Reserva simulada: no se ha creado ninguna cita real.</p>
          <p className="notice" lang="en">
            Simulated reservation — no real appointment created
          </p>
        </section>
      )}
      <h2>Fuentes</h2>
      <ul className="sources" aria-label="Fragmentos consultados">
        {!state.sources ? (
          <li>—</li>
        ) : state.sources.chunk_ids.length === 0 ? (
          <li>Sin fragmentos para esta pregunta.</li>
        ) : (
          sourceItems(state.sources).map((item, i) => (
            <li key={state.sources?.chunk_ids[i]}>
              <strong>{item.head}</strong>
              <span> {item.excerpt}</span>
            </li>
          ))
        )}
      </ul>
      <details className="reviewer">
        <summary>Panel de revisión</summary>
        <h3>Versiones</h3>
        <Rows className="versions" rows={state.versions ? versionRows(state.versions) : [["—", "—"]]} />
        <h3>Turnos</h3>
        <ol className="review" aria-label="Eventos técnicos por turno">
          {state.reviews.map((entry) => (
            <Review key={entry.key} entry={entry} />
          ))}
        </ol>
      </details>
      {href && (
        <p>
          <a href={href} download>
            Descargar JSON de la sesión
          </a>
        </p>
      )}
      <p className="actions">
        {canEnd(state) && (
          <button type="button" onClick={() => dispatch({ type: "end-pressed" })}>
            Terminar conversación
          </button>
        )}
        {canDelete(state) && (
          <button type="button" onClick={() => dispatch({ type: "delete-pressed" })}>
            Borrar esta conversación
          </button>
        )}
      </p>
    </aside>
  );
}

// One collapsed entry per turn: the lines a reviewer needs to follow it. Never hidden reasoning.
function Review({ entry }: { entry: ReviewEntry }) {
  return (
    <li>
      <details>
        <summary>{entry.detail ? `${entry.label} · ${entry.detail}` : entry.label}</summary>
        <ul>
          {entry.lines.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      </details>
    </li>
  );
}
