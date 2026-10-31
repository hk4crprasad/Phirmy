export type ScenarioId = "support" | "leads" | "booking" | "voice";
export const scenarios = {
  voice: {
    label: "Voice conversations",
    headline: "A familiar way to ask. A better way to help.",
    description:
      "Let customers speak naturally. Your voice agent listens, answers from your business knowledge, and keeps the conversation moving.",
    outcome: "A MORE NATURAL CONNECTION",
    business: "FORM & FIELD",
    kind: "A voice for your business.",
    source: "Visitor information",
    question: "Hi! Is there parking if I come for a tour?",
    answer:
      "Yes, visitor parking is available beside the main entrance. Let reception know you’re here for a tour, and our team will welcome you.",
    reply: "Perfect, thank you. I’ll see you there.",
    result: "A clear answer. One less thing to think about.",
    detail: "Visitor information · Conversation saved",
    steps: [
      "A customer speaks to the configured voice agent and asks about parking.",
      "The agent answers using the visitor information provided by the business.",
      "The conversation is available for the team to review. This illustrated experience uses prerecorded AI narration; it does not place a live call.",
    ],
  },
  support: {
    label: "Customer support",
    headline: "Good answers. From your knowledge.",
    description:
      "A visitor has a question. Your agent finds the relevant source and makes the answer easy to understand.",
    outcome: "ANSWER WITH CONTEXT",
    business: "FORM & FIELD",
    kind: "A thoughtful place to work.",
    source: "Membership guide",
    question: "Can I bring my team for just one day?",
    answer:
      "Absolutely. Our team day passes include a shared workspace, Wi-Fi, and meeting-room access. How many people are joining you?",
    reply: "There will be six of us.",
    result: "The right information. A warmer welcome.",
    detail: "Source: Team day passes · Membership guide",
    steps: [
      "A visitor asks whether the workspace offers a day pass for a team.",
      "The agent uses the connected membership guide to answer and links the source.",
      "The agent asks about team size so the conversation can continue with context.",
    ],
  },
  leads: {
    label: "Lead qualification",
    headline: "Turn interest into a meaningful introduction.",
    description:
      "Understand what a visitor needs, ask permission for a follow-up, and give your team a useful place to start.",
    outcome: "CONTEXT FOR YOUR TEAM",
    business: "FORM & FIELD",
    kind: "Room for your next big idea.",
    source: "Workspace options",
    question: "We’re looking for a private office for six.",
    answer:
      "I can help with that. Are you looking to move in soon, and would you like our team to follow up about available spaces?",
    reply: "Next month. Yes, please follow up with me.",
    result: "A new opportunity. With the details attached.",
    detail: "Team of 6 · Next month · Follow-up requested",
    steps: [
      "A visitor asks about a private office for six people.",
      "The agent asks about timing and requests permission for a team follow-up.",
      "After the visitor agrees, the follow-up and conversation context appear in the team inbox. This illustration uses fictional data.",
    ],
  },
  booking: {
    label: "Appointment booking",
    headline: "From “I’m interested” to “See you then.”",
    description:
      "Check a connected calendar, offer a time, and confirm the booking only after the visitor and scheduling provider do.",
    outcome: "A CONFIRMED NEXT STEP",
    business: "FORM & FIELD",
    kind: "Come find your kind of space.",
    source: "Connected calendar",
    question: "Could I book a tour tomorrow morning?",
    answer:
      "There’s a tour available at 10:00 AM. Shall I book that time for you?",
    reply: "Yes, please book the 10:00 AM tour.",
    result: "Your tour is booked. See you tomorrow.",
    detail: "Tomorrow · 10:00 AM · Calendar confirmed",
    steps: [
      "A visitor asks to book a tour tomorrow morning.",
      "The agent checks availability and reads back the proposed 10:00 AM time.",
      "The visitor explicitly confirms. After the calendar provider confirms, the booking appears as complete. This is an illustrated example, not a real booking.",
    ],
  },
} satisfies Record<
  ScenarioId,
  {
    label: string;
    headline: string;
    description: string;
    outcome: string;
    business: string;
    kind: string;
    source: string;
    question: string;
    answer: string;
    reply: string;
    result: string;
    detail: string;
    steps: string[];
  }
>;
