import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const receipt = {
  status: "received",
  reference: "2c0ebf3f-8cf2-4788-925a-2ecae4320668",
};
async function fill(page: import("@playwright/test").Page) {
  await page
    .getByRole("textbox", { name: "Your name", exact: true })
    .fill("Alex Morgan");
  await page
    .getByRole("textbox", { name: "Email address", exact: true })
    .fill("alex@example.com");
  await page.getByLabel("Company optional").fill("Studio & Co");
  await page.getByRole("radio", { name: "Voice + chat", exact: true }).check();
  await page
    .getByLabel("Tell us a little about your idea")
    .fill("We would love an agent to help customers book consultations.");
  await page.getByRole("checkbox").check();
}

test("home build CTAs lead to the real contact page", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("link", { name: "Build your agent", exact: true })
    .click();
  await expect(page).toHaveURL(/\/contact$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Let’s talk.",
  );
  await expect(
    page.getByRole("form", { name: "Contact Phirmy" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "support@phirmy.com", exact: true }),
  ).toHaveAttribute("href", "mailto:support@phirmy.com");
  await page.reload();
  await expect(
    page.getByRole("textbox", { name: "Your name", exact: true }),
  ).toBeVisible();
});

test("valid enquiry submits once and shows the correct confirmation", async ({
  page,
}) => {
  const bodies: any[] = [];
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/api/contact", async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ status: 202, json: receipt });
  });
  await page.goto("/contact");
  await fill(page);
  await page
    .getByRole("button", { name: "Let’s start a conversation" })
    .click();
  await expect(page.getByRole("status")).toContainText("Thanks, Alex.");
  await expect(page.getByRole("status")).toContainText("alex@example.com");
  await expect(page.getByRole("status")).toBeFocused();
  expect(bodies).toHaveLength(1);
  expect(bodies[0]).toMatchObject({
    name: "Alex Morgan",
    email: "alex@example.com",
    interest: "both",
    contact_permission: true,
  });
  expect(bodies[0]).not.toHaveProperty("recipient");
  expect(errors).toEqual([]);
});

test("required details and consent prevent an incomplete submission", async ({
  page,
}) => {
  let posts = 0;
  await page.route("**/api/contact", async (route) => {
    posts++;
    await route.fulfill({ status: 202, json: receipt });
  });
  await page.goto("/contact");
  await page
    .getByRole("button", { name: "Let’s start a conversation" })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Your name", exact: true }),
  ).toBeFocused();
  expect(posts).toBe(0);
  await fill(page);
  await page.getByRole("checkbox").uncheck();
  await page
    .getByRole("button", { name: "Let’s start a conversation" })
    .click();
  await expect(page.getByRole("checkbox")).toBeFocused();
  expect(posts).toBe(0);
});

test("a retry preserves details and reuses the same idempotency key", async ({
  page,
}) => {
  const keys: string[] = [];
  await page.route("**/api/contact", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    await route.fulfill(
      keys.length === 1
        ? { status: 503, json: { detail: "unavailable" } }
        : { status: 202, json: receipt },
    );
  });
  await page.goto("/contact");
  await fill(page);
  await page
    .getByRole("button", { name: "Let’s start a conversation" })
    .click();
  await expect(page.getByRole("alert")).toContainText("could not be received");
  await expect(page.getByRole("alert")).toBeFocused();
  await expect(
    page.getByRole("textbox", { name: "Your name", exact: true }),
  ).toHaveValue("Alex Morgan");
  await page
    .getByRole("button", { name: "Let’s start a conversation" })
    .click();
  await expect(page.getByRole("status")).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});

test("rate limit gives a useful message and direct email alternative", async ({
  page,
}) => {
  await page.route("**/api/contact", (route) =>
    route.fulfill({ status: 429, json: { detail: "limited" } }),
  );
  await page.goto("/contact");
  await fill(page);
  await page
    .getByRole("button", { name: "Let’s start a conversation" })
    .click();
  await expect(page.getByRole("alert")).toContainText("try again later");
  await expect(page.getByRole("alert").getByRole("link")).toHaveAttribute(
    "href",
    "mailto:support@phirmy.com",
  );
  await expect(page.getByRole("status")).toHaveCount(0);
});

for (const width of [390, 1440]) {
  test(`contact page at ${width}px is accessible, fits and uses the correct focus states`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/contact");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      result.violations.map((v) => ({
        id: v.id,
        targets: v.nodes.map((n) => n.target),
      })),
    ).toEqual([]);
    await page.route("**/api/contact", (route) =>
      route.fulfill({ status: 202, json: receipt }),
    );
    await fill(page);
    await page
      .getByRole("button", { name: "Let’s start a conversation" })
      .click();
    await expect(page.getByRole("status")).toBeVisible();
    const success = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      success.violations.map((v) => ({
        id: v.id,
        targets: v.nodes.map((n) => n.target),
      })),
    ).toEqual([]);
  });
}
