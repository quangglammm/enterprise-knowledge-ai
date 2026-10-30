"use client";

import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from "react";

import type { Identity } from "@/lib/api";

// Development identity sent as X-Tenant-ID / X-User-ID / X-User-Groups. The API accepts
// these only in local and test environments; real sign-in is SEC-01.
const DEFAULT_IDENTITY: Identity = { tenant: "bamboo-harbor", user: "an", groups: "all-staff" };
const STORAGE_KEY = "eka.identity";
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange); // another tab changed it
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // storage unavailable (private mode): the default identity still works
  }
}

function parse(stored: string | null): Identity {
  if (!stored) return DEFAULT_IDENTITY;
  try {
    return { ...DEFAULT_IDENTITY, ...(JSON.parse(stored) as Partial<Identity>) };
  } catch {
    return DEFAULT_IDENTITY;
  }
}

function store(identity: Identity): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
  } catch {
    // Not persisted; nothing else to do.
  }
  listeners.forEach((notify) => notify());
}

const IdentityContext = createContext<{
  identity: Identity;
  setIdentity: (identity: Identity) => void;
}>({ identity: DEFAULT_IDENTITY, setIdentity: store });

export function IdentityProvider({ children }: { children: ReactNode }) {
  // The server renders the default; the browser reads the stored identity after hydration.
  const stored = useSyncExternalStore(subscribe, readStored, () => null);
  const identity = useMemo(() => parse(stored), [stored]);

  return (
    <IdentityContext.Provider value={{ identity, setIdentity: store }}>
      {children}
    </IdentityContext.Provider>
  );
}

export function useIdentity() {
  return useContext(IdentityContext);
}
