const sections = new Set([
  "agents",
  "knowledge",
  "calls",
  "voice",
  "products",
  "widget",
  "campaigns",
  "inbox",
  "leads",
  "contacts",
  "billing",
  "developers",
  "integrations",
  "operations",
  "tools",
  "models",
  "appointments",
  "numbers",
  "team",
  "profile",
  "settings",
  "templates",
]);
export function isWorkspaceRoute(route: string[]) {
  return (
    !route.length ||
    (sections.has(route[0]) &&
      (route.length === 1 ||
        (route.length === 2 && ["agents", "knowledge"].includes(route[0]))))
  );
}
