import { useEffect, useRef } from "react";
import type { Bubble } from "../page/reducer";

export function Transcript({ bubbles }: { bubbles: Bubble[] }) {
  const list = useRef<HTMLOListElement>(null);
  const last = bubbles.at(-1);
  const size = last ? last.sentences.length : 0;
  // Follow the newest words inside the list only: the page itself never jumps.
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [bubbles.length, size]);
  return (
    <ol ref={list} className="transcript" aria-label="Conversación">
      {bubbles.map((bubble) => (
        <li key={bubble.id} className={bubble.role}>
          <span className="who">{bubble.role === "user" ? "Tú" : "Ana"}</span>
          <p>{bubble.sentences.join(" ") || "…"}</p>
        </li>
      ))}
    </ol>
  );
}
