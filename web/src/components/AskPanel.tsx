"use client";

import { useState } from "react";

import { ApiError, askQuestion, type AnswerMode } from "@/lib/api";

import { AnswerColumn, type ColumnState } from "./AnswerColumn";
import { useIdentity } from "./IdentityProvider";

type Choice = AnswerMode | "compare";

const CHOICES: { value: Choice; label: string }[] = [
  { value: "direct", label: "Direct" },
  { value: "workflow", label: "Workflow" },
  { value: "compare", label: "Compare both" },
];

// Questions from the demo corpus (datasets/corpus/v2) that show where the modes differ.
const EXAMPLES = [
  "Số ngày phép năm theo quy chế của công ty nhiều hơn mức của Bộ luật Lao động cho công việc bình thường bao nhiêu ngày?",
  "How fast must on-call engineers respond to a page, and what happens if a page is not acknowledged?",
  "Nhân viên được phụ cấp ăn uống bao nhiêu mỗi ngày khi đi công tác?",
];

function modesFor(choice: Choice): AnswerMode[] {
  return choice === "compare" ? ["direct", "workflow"] : [choice];
}

export function AskPanel() {
  const { identity } = useIdentity();
  const [question, setQuestion] = useState("");
  const [choice, setChoice] = useState<Choice>("compare");
  const [columns, setColumns] = useState<ColumnState[]>([]);

  async function run(mode: AnswerMode): Promise<ColumnState> {
    try {
      const { answer, latencyMs } = await askQuestion(question, mode, identity);
      return { mode, status: "done", answer, latencyMs };
    } catch (error) {
      const e =
        error instanceof ApiError ? error : new ApiError(0, "client_error", "Something failed.");
      return {
        mode,
        status: "error",
        error: { category: e.category, message: e.message, requestId: e.requestId },
      };
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    const modes = modesFor(choice);
    setColumns(modes.map((mode) => ({ mode, status: "loading" })));
    // Both modes run at once, so a comparison takes as long as the slower one.
    await Promise.all(
      modes.map(async (mode, i) => {
        const result = await run(mode);
        setColumns((current) => current.map((c, j) => (j === i ? result : c)));
      }),
    );
  }

  const busy = columns.some((c) => c.status === "loading");

  return (
    <div className="grid gap-10">
      <form onSubmit={submit} className="grid gap-4">
        <label htmlFor="question" className="text-3xl font-bold tracking-tight sm:text-4xl">
          What do you need to know?
        </label>
        <textarea
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder="Ask in Vietnamese or English, for example about leave, travel or runbooks."
          className="w-full max-w-3xl rounded-lg border border-ink/20 bg-white px-4 py-3 text-lg"
        />
        <div className="flex flex-wrap gap-2 text-sm">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setQuestion(example)}
              className="max-w-xs truncate rounded-full bg-mist-deep px-3 py-1 text-ink-soft hover:text-ink"
              title={example}
            >
              {example}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <fieldset className="flex rounded-lg border border-ink/20 bg-white p-1">
            <legend className="sr-only">How to answer</legend>
            {CHOICES.map(({ value, label }) => (
              <label
                key={value}
                className={`cursor-pointer rounded-md px-3 py-1.5 font-medium has-[:checked]:bg-ink has-[:checked]:text-mist has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-teal`}
              >
                <input
                  type="radio"
                  name="mode"
                  value={value}
                  checked={choice === value}
                  onChange={() => setChoice(value)}
                  className="sr-only"
                />
                {label}
              </label>
            ))}
          </fieldset>
          <button
            type="submit"
            disabled={busy || !question.trim()}
            className="rounded-lg bg-teal px-5 py-2 font-medium text-mist disabled:opacity-50"
          >
            {busy ? "Answering…" : "Get answer"}
          </button>
        </div>
      </form>

      {columns.length > 0 && (
        <div
          className={`grid gap-10 ${columns.length === 2 ? "lg:grid-cols-2 lg:divide-x lg:divide-ink/10 [&>*:last-child]:lg:pl-10" : "max-w-3xl"}`}
        >
          {columns.map((column) => (
            <AnswerColumn key={column.mode} state={column} />
          ))}
        </div>
      )}
    </div>
  );
}
