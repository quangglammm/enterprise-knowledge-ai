import { describe, expect, it } from "vitest";

import { routeStops, splitMarkers } from "./answer";
import type { AnswerResponse } from "./api";

function answer(overrides: Partial<AnswerResponse>): AnswerResponse {
  return {
    status: "answered",
    answer: "14 ngày [E1].",
    abstention_reason: null,
    citations: [],
    model_id: "Llama-3.3-70B-Instruct",
    prompt_version: "answer-v1",
    mode: "direct",
    sub_questions: [],
    usage: { steps: 2, model_calls: 1 },
    ...overrides,
  };
}

describe("routeStops", () => {
  it("shows direct RAG as one search then the answer", () => {
    expect(routeStops(answer({}))).toEqual(["Search", "Answer"]);
  });

  it("stops after the search when direct RAG abstained without calling the model", () => {
    const abstained = answer({ status: "insufficient_evidence", usage: { steps: 1, model_calls: 0 } });

    expect(routeStops(abstained)).toEqual(["Search", "No evidence"]);
  });

  it("shows the workflow's plan and one search per sub-question", () => {
    const workflow = answer({
      mode: "workflow",
      sub_questions: ["Số ngày phép năm?", "Ngày phép chuyển sang năm sau?"],
      usage: { steps: 4, model_calls: 2 },
    });

    expect(routeStops(workflow)).toEqual(["Plan", "Search 1", "Search 2", "Answer"]);
  });

  it("ends the workflow route in no evidence when it abstained", () => {
    const workflow = answer({
      mode: "workflow",
      status: "insufficient_evidence",
      sub_questions: ["Gửi xe?"],
      usage: { steps: 2, model_calls: 1 },
    });

    expect(routeStops(workflow)).toEqual(["Plan", "Search 1", "No evidence"]);
  });
});

describe("splitMarkers", () => {
  it("separates citation markers from text", () => {
    expect(splitMarkers("14 ngày [E1], chuyển 3 ngày [E2].")).toEqual([
      { text: "14 ngày " },
      { label: "E1" },
      { text: ", chuyển 3 ngày " },
      { label: "E2" },
      { text: "." },
    ]);
  });

  it("keeps text without markers whole", () => {
    expect(splitMarkers("300.000 đồng")).toEqual([{ text: "300.000 đồng" }]);
  });
});
