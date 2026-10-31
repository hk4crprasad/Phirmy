import policy from "../../../../config/legal.json";

export const legalPolicy = policy;
export const legalDocuments = policy.documents as Record<
  string,
  {
    title: string;
    sections: { title: string; body: string }[];
  }
>;
