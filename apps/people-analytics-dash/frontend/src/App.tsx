import { useState } from "react";

import { clearIdentity, getIdentity, setIdentity, type Identity } from "./api/client";
import { SsoStubLogin } from "./components/SsoStubLogin";
import { Records } from "./pages/Records";

export function App() {
  const [identity, setIdentityState] = useState<Identity | null>(() => getIdentity());

  if (identity === null) {
    return (
      <SsoStubLogin
        onSignIn={(next) => {
          setIdentity(next);
          setIdentityState(next);
        }}
      />
    );
  }

  return (
    <>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
              Insights Hub
            </p>
            <p className="text-lg font-semibold text-slate-900">people-analytics-dash</p>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-600">
              Signed in as <strong className="text-slate-900">{identity.user}</strong>
              <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                team {identity.team}
              </span>
              {identity.roles ? (
                <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                  roles {identity.roles}
                </span>
              ) : null}
              <span className="ml-2 text-xs text-amber-700">via SSO stub</span>
            </span>
            <button
              type="button"
              onClick={() => {
                clearIdentity();
                setIdentityState(null);
              }}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-8">
        <Records key={`${identity.user}/${identity.team}/${identity.roles}`} />
      </main>
    </>
  );
}
