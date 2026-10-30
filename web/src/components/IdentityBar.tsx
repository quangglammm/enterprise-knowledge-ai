"use client";

import { useState } from "react";

import { useIdentity } from "./IdentityProvider";

const FIELDS = [
  { key: "tenant", label: "Tenant" },
  { key: "user", label: "User" },
  { key: "groups", label: "Groups (comma-separated)" },
] as const;

export function IdentityBar() {
  const { identity, setIdentity } = useIdentity();
  const [open, setOpen] = useState(false);

  return (
    <div className="text-sm">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="rounded-full border border-ink/15 px-3 py-1 text-ink-soft hover:border-ink/40"
      >
        Acting as {identity.user} in {identity.tenant} ({identity.groups})
      </button>
      {open && (
        <form
          className="absolute right-6 z-10 mt-2 grid w-80 gap-3 rounded-lg border border-ink/15 bg-white p-4 shadow-sm"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            setIdentity({
              tenant: String(data.get("tenant") ?? ""),
              user: String(data.get("user") ?? ""),
              groups: String(data.get("groups") ?? ""),
            });
            setOpen(false);
          }}
        >
          <p className="text-ink-soft">
            Development identity. Documents outside these groups stay invisible.
          </p>
          {FIELDS.map(({ key, label }) => (
            <label key={key} className="grid gap-1">
              <span className="font-medium">{label}</span>
              <input
                name={key}
                defaultValue={identity[key]}
                required
                className="rounded border border-ink/20 px-2 py-1"
              />
            </label>
          ))}
          <button type="submit" className="rounded bg-ink px-3 py-1.5 font-medium text-mist">
            Use this identity
          </button>
        </form>
      )}
    </div>
  );
}
