import { routeStops, splitMarkers } from "@/lib/answer";
import type { AnswerMode, AnswerResponse } from "@/lib/api";

import { RouteLine } from "./RouteLine";

export interface ColumnState {
  mode: AnswerMode;
  status: "idle" | "loading" | "done" | "error";
  answer?: AnswerResponse;
  latencyMs?: number;
  error?: { category: string; message: string; requestId: string | null };
}

const TITLES: Record<AnswerMode, string> = {
  direct: "Direct answer",
  workflow: "Planned workflow",
};
const DESCRIPTIONS: Record<AnswerMode, string> = {
  direct: "One search, then one answer.",
  workflow: "Splits the question, searches each part, answers, then checks every claim.",
};

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

export function AnswerColumn({ state }: { state: ColumnState }) {
  const tone = state.mode === "direct" ? "teal" : "bamboo";
  const accent = tone === "teal" ? "text-teal" : "text-bamboo";

  return (
    <section aria-live="polite" aria-busy={state.status === "loading"} className="grid content-start gap-5">
      <header>
        <h2 className={`text-xl font-bold ${accent}`}>{TITLES[state.mode]}</h2>
        <p className="text-sm text-ink-soft">{DESCRIPTIONS[state.mode]}</p>
      </header>

      {state.status === "loading" && <p className="text-ink-soft">Searching the documents…</p>}

      {state.status === "error" && state.error && (
        <div className="border-l-4 border-brick pl-4">
          <p className="font-medium text-brick">{state.error.message}</p>
          <p className="text-sm text-ink-soft">
            {state.error.category}
            {state.error.requestId && `, request ${state.error.requestId}`}
          </p>
        </div>
      )}

      {state.status === "done" && state.answer && (
        <Answer answer={state.answer} latencyMs={state.latencyMs ?? 0} tone={tone} />
      )}
    </section>
  );
}

function Answer({
  answer,
  latencyMs,
  tone,
}: {
  answer: AnswerResponse;
  latencyMs: number;
  tone: "teal" | "bamboo";
}) {
  const markerColor = tone === "teal" ? "bg-teal" : "bg-bamboo";
  return (
    <>
      <RouteLine stops={routeStops(answer)} tone={tone} />

      {answer.mode === "workflow" && answer.sub_questions.length > 0 && (
        <div>
          <h3 className="text-sm font-medium">Searched as</h3>
          <ol className="mt-1 list-decimal pl-5 text-sm text-ink-soft">
            {answer.sub_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        </div>
      )}

      {answer.status === "answered" && answer.answer ? (
        <p className="text-lg leading-relaxed">
          {splitMarkers(answer.answer).map((part, i) =>
            "label" in part ? (
              <a
                key={i}
                href={`#${answer.mode}-${part.label}`}
                className={`mx-0.5 rounded px-1 align-[0.15em] text-xs font-bold text-mist ${markerColor}`}
              >
                {part.label}
              </a>
            ) : (
              <span key={i}>{part.text}</span>
            ),
          )}
        </p>
      ) : answer.verification.verified === false ? (
        <p className="text-lg text-ink-soft">
          An answer was drafted but withheld: the evidence did not support all of it, even after
          a revision. Try a narrower question.
        </p>
      ) : (
        <p className="text-lg text-ink-soft">
          The documents you can read do not answer this. Try rephrasing, or upload the document
          that does.
        </p>
      )}

      {answer.citations.length > 0 && (
        <div>
          <h3 className="text-sm font-medium">Sources</h3>
          <ul className="mt-1 grid gap-1 text-sm">
            {answer.citations.map((c) => (
              <li key={c.chunk_id} id={`${answer.mode}-${c.label}`} className="flex gap-2">
                <span className="font-bold">{c.label}</span>
                <span>
                  {c.title}
                  {c.section && <span className="text-ink-soft">, {c.section}</span>}
                  {c.page !== null && <span className="text-ink-soft">, page {c.page}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <dl className="grid grid-cols-3 gap-3 border-t border-ink/10 pt-3 text-sm">
        <div>
          <dt className="text-ink-soft">Model calls</dt>
          <dd className="text-lg font-bold">{answer.usage.model_calls}</dd>
        </div>
        <div>
          <dt className="text-ink-soft">Steps</dt>
          <dd className="text-lg font-bold">{answer.usage.steps}</dd>
        </div>
        <div>
          <dt className="text-ink-soft">Time</dt>
          <dd className="text-lg font-bold">{seconds(latencyMs)}</dd>
        </div>
      </dl>
    </>
  );
}
