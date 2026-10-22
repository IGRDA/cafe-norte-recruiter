import { useEffect } from "react";
import { Composer } from "./components/Composer";
import { Header } from "./components/Header";
import { Panel } from "./components/Panel";
import { Signals } from "./components/Signals";
import { Transcript } from "./components/Transcript";
import type { Ports } from "./page/effects";
import { isRtl, languageBars, latestSignal, signalStatus, type State } from "./page/reducer";
import { usePage } from "./page/usePage";

interface Props {
  requested: State["requested"];
  ports: Ports;
}

export function App({ requested, ports }: Props) {
  const [state, dispatch] = usePage(requested, ports);
  // Screen readers pronounce the page in the session's language, which can switch (D53).
  const rtl = isRtl(state);
  useEffect(() => {
    document.documentElement.lang = state.language;
    document.documentElement.dir = rtl ? "rtl" : "ltr";
  }, [state.language, rtl]);
  return (
    <main id="app">
      <Header state={state} dispatch={dispatch} />
      <section className="layout">
        <section className="conversation" aria-label="Conversación con Ana">
          <Transcript bubbles={state.transcript} />
          <Composer state={state} dispatch={dispatch} />
          <Signals
            status={signalStatus(state)}
            latest={latestSignal(state)}
            languages={(p) => languageBars(state, p)}
          />
          {state.error && (
            <p className="error" role="alert">
              {state.error}
            </p>
          )}
        </section>
        <Panel state={state} dispatch={dispatch} />
      </section>
    </main>
  );
}
