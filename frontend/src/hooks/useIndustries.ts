import { useEffect, useState } from "react";

import { fetchIndustries, type Industry } from "../api";

export type IndustriesStatus = "loading" | "loaded" | "error";

interface Settled {
  attempt: number;
  industries: Industry[] | null;
}

/** Every industry, fetched once (and again only on retry). */
export function useIndustries(): {
  status: IndustriesStatus;
  industries: Industry[];
  retry: () => void;
} {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchIndustries(controller.signal).then(
      (industries) => {
        if (!controller.signal.aborted) setSettled({ attempt, industries });
      },
      () => {
        if (!controller.signal.aborted)
          setSettled({ attempt, industries: null });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  const current = settled?.attempt === attempt ? settled : null;
  const status: IndustriesStatus =
    current === null ? "loading" : current.industries ? "loaded" : "error";

  return {
    status,
    industries: current?.industries ?? [],
    retry: () => setAttempt((n) => n + 1),
  };
}
