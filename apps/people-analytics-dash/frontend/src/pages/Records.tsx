import { useEffect, useState } from "react";

import { fetchRecords, type HeadcountRecord } from "../api/client";
import { RecordsTable } from "../components/RecordsTable";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; records: HeadcountRecord[] };

export function Records() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchRecords()
      .then((records) => {
        if (!cancelled) {
          setState({ status: "ready", records });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : String(error);
          setState({ status: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading records…
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <p
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
      >
        Could not load records: {state.message}
      </p>
    );
  }
  return (
    <section>
      <div className="mb-4 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Headcount</h1>
        <span className="text-xs text-slate-500">
          from the <code>warehouse</code> connection via <code>/api/records</code>
        </span>
      </div>
      <RecordsTable records={state.records} />
    </section>
  );
}
