import { useCallback, useEffect, useState } from "react";

export type QueryState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: Error };

/**
 * Minimal fetch hook. Deliberately tiny: no caching layer, no retries that hide
 * failures, no background polling of user data.
 */
export function useQuery<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<QueryState<T>>({ status: "loading", data: null, error: null });

  const run = useCallback(() => {
    let active = true;
    setState({ status: "loading", data: null, error: null });
    fetcher()
      .then((data) => {
        if (active) setState({ status: "ready", data, error: null });
      })
      .catch((error: unknown) => {
        if (active) {
          setState({
            status: "error",
            data: null,
            error: error instanceof Error ? error : new Error("Unknown error"),
          });
        }
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(run, [run]);

  return state;
}
