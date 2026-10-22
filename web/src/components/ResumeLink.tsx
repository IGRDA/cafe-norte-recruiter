import type { State } from "../page/reducer";

export function ResumeLink({ state }: { state: State }) {
  if (!state.resumeUrl || state.page === "deleted") return null;
  return (
    <p className="notice resume">
      Guarda este enlace para continuar más tarde (válido 7 días):{" "}
      <a href={state.resumeUrl}>{`${location.origin}${state.resumeUrl}`}</a>
    </p>
  );
}
