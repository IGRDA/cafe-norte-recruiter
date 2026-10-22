import { Composer } from "./components/Composer";
import { Header } from "./components/Header";
import { Panel } from "./components/Panel";
import { Transcript } from "./components/Transcript";
import type { Ports } from "./page/effects";
import type { State } from "./page/reducer";
import { usePage } from "./page/usePage";

interface Props {
  requested: State["requested"];
  ports: Ports;
}

export function App({ requested, ports }: Props) {
  const [state, dispatch] = usePage(requested, ports);
  return (
    <main id="app">
      <Header state={state} dispatch={dispatch} />
      <section className="layout">
        <div className="conversation">
          <Transcript bubbles={state.transcript} />
          <Composer state={state} dispatch={dispatch} />
          {state.error && (
            <p className="error" role="alert">
              {state.error}
            </p>
          )}
        </div>
        <Panel state={state} dispatch={dispatch} />
      </section>
    </main>
  );
}
