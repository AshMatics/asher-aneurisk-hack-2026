import { useEffect, useRef } from "react";

/** Call `fn` every `ms` while `active`; the next call is scheduled after the previous finishes. */
export function usePoll(fn: () => Promise<unknown>, active: boolean, ms: number): void {
  const latest = useRef(fn);
  useEffect(() => {
    latest.current = fn;
  }, [fn]);
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await latest.current();
      } catch {
        // the caller shows its own error; keep polling
      } finally {
        if (!stopped) timer = setTimeout(tick, ms);
      }
    };
    timer = setTimeout(tick, ms);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [active, ms]);
}
