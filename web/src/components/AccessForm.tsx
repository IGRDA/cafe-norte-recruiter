import { showAccess, type Action, type State } from "../page/reducer";

interface Props {
  state: State;
  dispatch: (action: Action) => void;
}

export function AccessForm({ state, dispatch }: Props) {
  if (!showAccess(state)) return null;
  return (
    <form
      className="access"
      autoComplete="off"
      onSubmit={(event) => {
        event.preventDefault();
        const code = new FormData(event.currentTarget).get("code");
        dispatch({ type: "code-submitted", code: typeof code === "string" ? code : "" });
      }}
    >
      <label htmlFor="code">Código de acceso</label>
      <input id="code" name="code" maxLength={128} required />
      <button type="submit" disabled={state.access === "checking"}>
        Entrar
      </button>
    </form>
  );
}
