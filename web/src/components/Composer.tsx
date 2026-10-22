import { canSend, canTalk, canType, talkPressed, type Action, type State } from "../page/reducer";

interface Props {
  state: State;
  dispatch: (action: Action) => void;
}

export function Composer({ state, dispatch }: Props) {
  const pressed = talkPressed(state);
  return (
    <form
      className="composer"
      autoComplete="off"
      onSubmit={(event) => {
        event.preventDefault();
        dispatch({ type: "text-submitted" });
      }}
    >
      <label htmlFor="text" className="visually-hidden">
        Tu mensaje
      </label>
      <input
        id="text"
        name="text"
        maxLength={2000}
        placeholder="Escribe a Ana…"
        required
        value={state.draft}
        disabled={!canType(state)}
        onChange={(event) => dispatch({ type: "draft-changed", text: event.target.value })}
      />
      <button type="submit" disabled={!canSend(state)}>
        Enviar
      </button>
      {state.voiceOffered && (
        <button
          type="button"
          aria-pressed={pressed}
          disabled={!canTalk(state)}
          title="Voz alojada: Daily + Deepgram + ElevenLabs"
          onClick={() => dispatch({ type: "talk-pressed" })}
        >
          {pressed ? "⏹ Parar" : "🎙 Hablar"}
        </button>
      )}
    </form>
  );
}
