import type { AnswerResponse } from "./api";

// The stops an answer actually went through, for its route line. Derived from the mode,
// the sub-questions and whether the model was called, never guessed.
export function routeStops(answer: AnswerResponse): string[] {
  if (answer.mode === "direct") {
    return ["Search", answer.status === "answered" ? "Answer" : "No evidence"];
  }
  const searches = answer.sub_questions.map((_, i) => `Search ${i + 1}`);
  const { verified, revisions } = answer.verification;
  if (verified === null) {
    // Nothing was verified: no evidence, or the model itself abstained.
    return ["Plan", ...searches, answer.status === "answered" ? "Answer" : "No evidence"];
  }
  const revision = revisions > 0 ? ["Check", "Revise"] : [];
  return ["Plan", ...searches, "Answer", ...revision, verified ? "Verified" : "Withheld"];
}

export type AnswerPart = { text: string } | { label: string };

// Split "… [E1] …" so citation markers can render as links to their sources.
export function splitMarkers(text: string): AnswerPart[] {
  const parts: AnswerPart[] = [];
  let last = 0;
  for (const match of text.matchAll(/\[(E\d+)\]/g)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    parts.push({ label: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}
