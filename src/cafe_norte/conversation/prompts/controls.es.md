# Replies to explicit requests (ana_v19, es)

One `key: sentence` per line, spoken word for word by the runtime: `human` when `explicit_controls`
detects the request (`conversation/signals.py`), `time_cap` when a turn carries the session past
its active-time cap, `goodbye` when the candidate says goodbye after booking (D46). No brackets:
these are read aloud.
`controls.en.md` has exactly the same keys.

human: Entiendo. Ahora mismo no puedo pasarte con una persona, pero la entrevista será con alguien del equipo. He dejado anotado que quieres hablar con una persona; en esta demostración no se avisa a nadie real. Puedes dejar la llamada cuando quieras. ¿Seguimos?
time_cap: Hemos llegado al tiempo máximo de esta conversación. He guardado lo que me has contado y el equipo lo revisará. ¡Gracias por tu tiempo y hasta pronto!
goodbye: ¡Gracias por tu tiempo! Tu entrevista queda reservada. ¡Hasta pronto!
