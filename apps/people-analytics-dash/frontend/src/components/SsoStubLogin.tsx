import { useState, type FormEvent } from "react";

import type { Identity } from "../api/client";

const field =
  "mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm " +
  "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200";

export function SsoStubLogin({ onSignIn }: { onSignIn: (identity: Identity) => void }) {
  const [user, setUser] = useState("dev");
  const [team, setTeam] = useState("people-analytics");
  const [roles, setRoles] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSignIn({ user: user.trim(), team: team.trim(), roles: roles.trim() });
  }

  return (
    <main className="mx-auto mt-16 max-w-md px-4">
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
          Insights Hub · people-analytics-dash
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">Sign in</h1>
        <p className="mt-4 rounded-md border-l-4 border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
          <strong>SSO stub, development only.</strong> In production the SSO proxy authenticates you
          and sets the <code>X-Insights-User</code>, <code>X-Insights-Team</code> and{" "}
          <code>X-Insights-Roles</code> headers on every request. This form stands in for it; the
          app trusts the same headers.
        </p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block text-sm font-medium text-slate-700">
            User
            <input
              className={field}
              value={user}
              onChange={(e) => setUser(e.target.value)}
              required
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Team
            <input
              className={field}
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              required
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Roles <span className="font-normal text-slate-500">(comma-separated, optional)</span>
            <input className={field} value={roles} onChange={(e) => setRoles(e.target.value)} />
          </label>
          <button
            type="submit"
            className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          >
            Sign in
          </button>
        </form>
      </div>
    </main>
  );
}
