// One shared event stream per tab. Every panel that live-updates subscribes
// here instead of opening its own EventSource — N panels, one connection,
// so the single hub container is never wedged behind idle streams.
type Cb = () => void;

const subs = new Set<Cb>();
let es: EventSource | null = null;

export function subscribeStream(cb: Cb): () => void {
  subs.add(cb);
  if (!es) {
    es = new EventSource("/stream");
    es.onmessage = () => {
      subs.forEach((f) => {
        try {
          f();
        } catch {
          /* one panel's failure never breaks the others */
        }
      });
    };
  }
  return () => {
    subs.delete(cb);
    if (subs.size === 0) {
      es?.close();
      es = null;
    }
  };
}
