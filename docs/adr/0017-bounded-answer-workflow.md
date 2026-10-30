# ADR-0017: A bounded plan–retrieve–answer workflow, chosen per request

- Status: Accepted
- Date: 2026-10-30

## Context

AGENT-01 requires three things:
- direct questions avoid unnecessary agent calls;
- complex questions follow a documented workflow;
- step limits and timeouts are enforced.

Plan revision 10 asks for an explicit state machine. The safety rules add a tool allowlist, limits on steps, model calls and wall-clock time, and the condition that "the agent path must justify itself in the evaluation".

On benchmark v2, direct RAG misses mostly come from cross-lingual and multi-part questions, where one search returns the wrong part or the wrong language (EVAL-02). The user's direction is to add the workflow as a mode to compare with standard RAG, chosen explicitly (and from a UI), not routed automatically.

## Options considered

Routing:
1. **The caller picks the mode, with a configured default.** No routing errors, and both modes stay comparable on the same questions.
2. **A rule-based router.** Free, but its accuracy is one more variable before the workflow is shown to help.
3. **An LLM router.** Every direct question pays an extra call.

Workflow:
1. **Plan → retrieve per part → answer once.** At most 3 model calls.
2. **An iterative retrieve loop** in the ReAct style. More calls, harder to bound, and overlaps AGENT-02's verification.

## Decision

Routing option 1 and workflow option 1.

- **Modes** (`agents/modes.py`): `POST /v1/answers` accepts `mode` (`direct` or `workflow`); without it, `EKA_ANSWER_MODE` (default `direct`) decides. Both modes return the same answer shape plus `mode`, `sub_questions` and `usage` (steps, model calls), so a client can compare them. Direct mode is unchanged `AnswerQuestion`: no planner, at most one answer call and its repair.
- **Workflow** (`agents/workflow.py`, an explicit state machine):

  ```
  PLANNING → RETRIEVING (×n) → ANSWERING → DONE
                 └→ ABSTAINED (no usable evidence: no answer call)
  ```

  - **Planning:** one model call with prompt `planner-v1` returns 1 to `EKA_WORKFLOW_MAX_SUB_QUESTIONS` (default 3) standalone sub-questions in the question's language. The planner sees only the user's question, never documents, so retrieved text cannot choose the searches. An unusable plan falls back to the question itself.
  - **Retrieving:** each sub-question goes through `SearchKnowledge` with `answer_top_k`, so tenant and ACL filters stay in the query and `ensure_accessible` still checks the results. Evidence is merged round-robin by rank, which gives each part its best chunks, then deduplicated and capped at `EKA_WORKFLOW_MAX_EVIDENCE` (default 8). The evidence gate (`EKA_ANSWER_MIN_SCORE`) then applies.
  - **Answering:** `GenerateAnswer` answers the original question, with the same prompt, parser, citation checks and single repair as direct mode.
- **Limits** (`WorkflowLimits`):
  - **Model calls:** at most 3 (plan, answer, repair).
  - **Steps:** at most `max_sub_questions + 2`. Planning, each retrieval and answering count; outcomes do not.
  - **Deadline:** one deadline for the whole run, `EKA_WORKFLOW_TIMEOUT_SECONDS` (default 60).
  - **Validation:** limits that could not complete a run are rejected.
  - **Failures:** an invalid transition raises `InvalidWorkflowTransitionError`; exceeding a limit raises `WorkflowLimitError` (502), and the deadline raises `WorkflowTimeoutError` (504). None of these returns a partial answer.
- **Tools:** search and generation only, fixed in code.
- **Logging:** logs record states, counts and fallbacks, never text.
- **Evaluation:** `scripts/run_answer_eval.py --mode workflow` runs the EVAL-02 evaluation through the workflow. Reports record the mode, workflow limits, model calls and planner tokens next to answer and judge tokens.

## Results (2026-10-30)

On benchmark v2 the workflow is not better than direct RAG. Write-up: `docs/evaluation/agent01-direct-vs-workflow.md`.

- **Outcomes:** they differ on 1 of 115 questions, and the workflow is worse there (q038 abstained). Correct-or-partial is 93% against 94%.
- **Cost:** twice the model calls (230 against 115) and 20.6k planner input tokens.
- **Why:** the planner keeps 97 questions as a single part, which reproduces direct exactly. Direct already answers 7 of the 8 multi-document questions, and the real misses are cross-lingual retrieval failures that `planner-v1` does not address.

`direct` stays the default. A `planner-v2` that adds a query in the other language is the next hypothesis.

## Consequences

- **Cost:** the workflow costs one more model call (the planner, about 190 input tokens) and up to 3× the searches. It is worth enabling only if the direct-vs-workflow comparison on benchmark v2 shows a gain where direct RAG fails (multi-part and cross-lingual questions) without losses elsewhere.
- **Default:** `EKA_ANSWER_MODE` stays `direct` until that comparison is recorded. An automatic router is a later decision, made on that data.
- **Safety:** retrieved text cannot change the plan, but it is still untrusted inside the answer prompt, as in direct mode. AGENT-02 adds verification of the final answer against its evidence.
- **Limits:** the planner prompt, `max_sub_questions` and `max_evidence` are evaluation variables; a prompt change bumps `PLANNER_PROMPT_VERSION`.
