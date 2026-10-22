import { useEffect, useRef } from "react";
import type { Bubble } from "../page/reducer";

const NEAR_BOTTOM_PX = 48;

export function Transcript({ bubbles }: { bubbles: Bubble[] }) {
  const list = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const last = bubbles.at(-1);
  const size = last ? last.sentences.length : 0;
  // Follow the newest words inside the list only (the page never jumps), unless the reader has
  // scrolled up to read something earlier.
  useEffect(() => {
    const element = list.current;
    if (element && following.current) element.scrollTop = element.scrollHeight;
  }, [bubbles.length, size]);
  return (
    // A log: assistive technology reads new bubbles as they arrive, politely.
    <div
      ref={list}
      className="transcript"
      role="log"
      aria-label="Conversación"
      tabIndex={0}
      onScroll={(event) => {
        const element = event.currentTarget;
        following.current = element.scrollHeight - element.scrollTop - element.clientHeight < NEAR_BOTTOM_PX;
      }}
    >
      <ol>
        {bubbles.map((bubble) => (
          <li key={bubble.id} className={bubble.role}>
            <span className="who">{bubble.role === "user" ? "Tú" : "Ana"}</span>
            <p>{bubble.sentences.join(" ") || "…"}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
