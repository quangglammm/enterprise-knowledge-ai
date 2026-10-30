"use client";

import { useEffect, useState } from "react";

import { ApiError, getJob, uploadDocument, type Job, type UploadResponse } from "@/lib/api";

import { useIdentity } from "./IdentityProvider";

interface Upload {
  filename: string;
  result: UploadResponse;
  job: Job | null;
}

const POLL_MS = 1500;
const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Waiting for the worker",
  running: "Being indexed",
  succeeded: "Ready to search",
  failed: "Could not be indexed",
};
const STATUS_COLOR: Record<Job["status"], string> = {
  queued: "bg-amber",
  running: "bg-amber",
  succeeded: "bg-bamboo",
  failed: "bg-brick",
};

function finished(job: Job | null): boolean {
  return job === null || job.status === "succeeded" || job.status === "failed";
}

export function DocumentsPanel() {
  const { identity } = useIdentity();
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // Poll unfinished jobs until each succeeds or fails.
  useEffect(() => {
    if (uploads.every((u) => finished(u.job))) return;
    const timer = window.setTimeout(async () => {
      const next = await Promise.all(
        uploads.map(async (u) =>
          finished(u.job) || !u.job
            ? u
            : { ...u, job: await getJob(u.job.id, identity).catch(() => u.job) },
        ),
      );
      setUploads(next);
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [uploads, identity]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (!(file instanceof File) || file.size === 0) return;
    setSending(true);
    setError(null);
    try {
      const result = await uploadDocument(
        file,
        String(data.get("groups") ?? ""),
        identity,
        String(data.get("title") ?? ""),
      );
      setUploads((current) => [{ filename: file.name, result, job: result.job }, ...current]);
      form.reset();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message} (${e.category})` : "The upload failed.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="grid gap-10">
      <form onSubmit={submit} className="grid max-w-3xl gap-4">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Add a document</h1>
        <p className="text-ink-soft">
          PDF, Word, HTML, Markdown or text. The worker indexes it in the background; it becomes
          searchable when it shows as ready.
        </p>
        <input
          name="file"
          type="file"
          required
          accept=".pdf,.docx,.html,.htm,.md,.txt"
          className="rounded-lg border border-ink/20 bg-white px-3 py-2"
        />
        <label className="grid gap-1">
          <span className="font-medium">Who can read it</span>
          <input
            name="groups"
            defaultValue="all-staff"
            required
            className="rounded-lg border border-ink/20 bg-white px-3 py-2"
          />
          <span className="text-sm text-ink-soft">
            Comma-separated groups. You can only share with groups you belong to.
          </span>
        </label>
        <label className="grid gap-1">
          <span className="font-medium">Title (optional)</span>
          <input name="title" className="rounded-lg border border-ink/20 bg-white px-3 py-2" />
        </label>
        <div>
          <button
            type="submit"
            disabled={sending}
            className="rounded-lg bg-teal px-5 py-2 font-medium text-mist disabled:opacity-50"
          >
            {sending ? "Uploading…" : "Upload document"}
          </button>
        </div>
        {error && <p className="border-l-4 border-brick pl-4 text-brick">{error}</p>}
      </form>

      {uploads.length > 0 && (
        <section aria-live="polite" className="max-w-3xl">
          <h2 className="text-xl font-bold">Uploaded in this session</h2>
          <ul className="mt-3 divide-y divide-ink/10">
            {uploads.map((u) => (
              <li key={u.job?.id ?? u.result.document.id} className="flex items-center gap-3 py-3">
                <span
                  className={`size-3 shrink-0 rounded-full ${u.job ? STATUS_COLOR[u.job.status] : "bg-bamboo"}`}
                  aria-hidden
                />
                <span className="grow">
                  <span className="font-medium">{u.filename}</span>
                  <span className="block text-sm text-ink-soft">
                    {u.job
                      ? `${STATUS_TEXT[u.job.status]}${u.job.error_category ? `: ${u.job.error_category}` : ""}, attempt ${u.job.attempts} of ${u.job.max_attempts}`
                      : "Already indexed: identical content was uploaded before"}
                  </span>
                </span>
                <span className="text-sm text-ink-soft">version {u.result.document.version}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
