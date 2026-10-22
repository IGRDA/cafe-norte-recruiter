import type { Language } from "../api/client";
import { startLabel, storeName, type Action, type State } from "../page/reducer";
import { AccessForm } from "./AccessForm";
import { ResumeLink } from "./ResumeLink";

interface Props {
  state: State;
  dispatch: (action: Action) => void;
}

export function Header({ state, dispatch }: Props) {
  return (
    <header>
      <h1 className="brand">
        <img src="/logo-mark.svg" alt="" width="40" height="40" /> Ana · <span>{storeName(state)}</span>
      </h1>
      <p className="notice">
        Demostración ficticia de selección. Usa datos inventados. Se guardan los textos y transcripciones; no se
        graba audio.
      </p>
      <form
        className="chooser"
        onSubmit={(event) => {
          event.preventDefault();
          dispatch({ type: "chooser-submitted" });
        }}
      >
        <label htmlFor="store">Tienda</label>
        <select
          id="store"
          value={state.chooser.store}
          onChange={(event) => dispatch({ type: "chooser-changed", store: event.target.value })}
        >
          {state.stores.map((store) => (
            <option key={store.config_id} value={store.config_id}>
              {store.store_name}
            </option>
          ))}
        </select>
        <label htmlFor="language">Idioma · Language</label>
        <select
          id="language"
          value={state.chooser.language}
          onChange={(event) => dispatch({ type: "chooser-changed", language: event.target.value as Language })}
        >
          <option value="es">Español</option>
          <option value="en">English</option>
        </select>
        <button type="submit">{startLabel(state)}</button>
      </form>
      <p className="status" aria-live="polite">
        {state.status}
      </p>
      <ResumeLink state={state} />
      <AccessForm state={state} dispatch={dispatch} />
    </header>
  );
}
