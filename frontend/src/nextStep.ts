import { EmployerView, Me, TrackerRow } from "./api";

// What the "Next step" button does for each step of the guided path.
// kind "chat" sends a message to the boss; "employers" opens the Employers tab; "focus" focuses the chat box.
export type NextAction = { step: number | null; label: string; hint: string; kind: "chat" | "employers" | "focus"; message?: string };

export function nextAction(me: Me | null, tracker: TrackerRow[], employers: EmployerView | null): NextAction | null {
  if (!me) return null;
  const tracked = tracker.map((t) => t.company);
  const list = tracked.slice(0, 15).join(", ");
  return actionFor(me.next_step, tracked.length, list, !!employers);
}

export function actionFor(step: number | null, nTracked: number, list: string, hasTable: boolean): NextAction {
  switch (step) {
    case 1:
      return { step, label: "Tell me where you want to work", hint: "Type a city and country in the chat.", kind: "focus" };
    case 2:
      return { step, label: "Get the employment reports →", hint: "Find the top MBA programs' reports for your city.", kind: "chat",
        message: "Let's get the employment reports. Please find them for me." };
    case 3:
      return { step, label: "Build my employer table →", hint: "Group the employers from the reports by industry.", kind: "chat",
        message: "Please summarize the employers by industry." };
    case 4:
      return nTracked > 0
        ? { step, label: `Research my ${nTracked} tracked compan${nTracked === 1 ? "y" : "ies"} →`,
            hint: "Salary, MBA roles, locations, visa sponsorship and recruiting timelines.", kind: "chat",
            message: `Please research my tracked companies: ${list}.` }
        : { step, label: hasTable ? "Pick companies to research →" : "Research companies →",
            hint: "Tick companies in the Employers table, then press Research selected.", kind: hasTable ? "employers" : "chat",
            message: "Which companies should I research?" };
    case 5:
      return { step, label: hasTable ? "Pick companies to track →" : "Build my tracker →",
        hint: "Choose 5–15 companies with + Track in the Employers table.", kind: hasTable ? "employers" : "chat",
        message: "Help me pick 5-15 companies for my tracker." };
    case 6:
      return { step, label: "Find job postings →", hint: "Check your tracked companies' careers pages for intern / MBA roles.",
        kind: "chat", message: "Let's find job postings for my tracked companies." };
    default:
      return { step: null, label: "Check for new postings →", hint: "All steps done. Re-check your tracked companies every few days.",
        kind: "chat", message: "Check my tracked companies for new job postings." };
  }
}
