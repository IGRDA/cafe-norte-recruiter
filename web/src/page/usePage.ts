// useReducer with effects as data: each step keeps the effects its action asked for, and a
// useEffect hands them to the runner. The reducer stays pure under StrictMode's double call, and
// a step's effects run once (the ref remembers the last batch it ran).
import { useEffect, useReducer, useRef } from "react";
import { createRunner, type Ports, type Runner } from "./effects";
import { initial, reduce, type Action, type Effect, type State } from "./reducer";

interface Step {
  state: State;
  effects: readonly Effect[];
}

function step(previous: Step, action: Action): Step {
  const effects: Effect[] = [];
  const state = reduce(previous.state, action, (effect) => effects.push(effect));
  return { state, effects };
}

export function usePage(requested: State["requested"], ports: Ports): [State, (action: Action) => void] {
  const [current, dispatch] = useReducer(step, requested, (r) => ({
    state: initial(r),
    effects: [{ type: "load-boot" }] as const,
  }));
  const runner = useRef<Runner | null>(null);
  const ran = useRef<readonly Effect[] | null>(null);

  useEffect(() => {
    runner.current = createRunner(ports, dispatch);
    return () => {
      runner.current?.dispose();
      runner.current = null;
    };
  }, [ports]);

  useEffect(() => {
    if (ran.current === current.effects || !runner.current) return;
    ran.current = current.effects;
    for (const effect of current.effects) runner.current.run(effect);
  }, [current.effects]);

  return [current.state, dispatch];
}
