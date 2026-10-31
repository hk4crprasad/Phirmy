import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const scenarios = [
  "Customer support",
  "Voice conversations",
  "Lead qualification",
  "Appointment booking",
];

test("desktop page, navigation, FAQ and app links work without errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName(
    "Your business. Always there.",
  );
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "FAQs" })
    .click();
  const question = page
    .locator("summary")
    .filter({ hasText: "How does pricing work?" });
  await question.click();
  await expect(page.locator("details[open]")).toContainText(
    "Plans and paid activation are being finalized",
  );
  await question.click();
  await expect(page.locator("details[open]")).toHaveCount(0);
  for (const link of await page.locator('a[href^="#"]').all()) {
    const href = await link.getAttribute("href");
    if (href && href !== "#") await expect(page.locator(href)).toHaveCount(1);
  }
  await expect(
    page.getByRole("link", { name: "Build your agent", exact: true }),
  ).toHaveAttribute("href", "/contact");
  await expect(
    page.getByRole("link", { name: "Setup guide", exact: true }),
  ).toHaveAttribute("href", "#how-it-works");
  expect(errors).toEqual([]);
});

test("all Remotion scenarios play, seek, pause, restart, and explain their outcomes", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "See it in action" }).click();
  await expect(page.getByRole("tablist")).toBeVisible();
  for (const scenario of scenarios) {
    await page.getByRole("tab", { name: scenario, exact: true }).click();
    await expect(
      page.getByRole("tab", { name: scenario, exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await page
      .getByRole("button", { name: "Play walkthrough", exact: true })
      .click();
    const timeline = page.getByRole("slider", { name: "Walkthrough timeline" });
    await expect
      .poll(async () => Number(await timeline.inputValue()))
      .toBeGreaterThan(10);
    await page
      .getByRole("button", { name: "Pause walkthrough", exact: true })
      .click();
    await expect(page.getByRole("button", { name: "Play walkthrough", exact: true })).toBeVisible();
    // Let the player's final queued frame event reach React before sampling.
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    const stopped = Number(await timeline.inputValue());
    await page.waitForTimeout(120);
    expect(Number(await timeline.inputValue())).toBe(stopped);
    const finalFrame = (await timeline.getAttribute("max"))!;
    await timeline.fill(finalFrame);
    await expect(timeline).toHaveValue(finalFrame);
    await expect(page.locator(".demo-screen")).toContainText(
      scenario === "Appointment booking"
        ? "Your tour is booked."
        : scenario === "Lead qualification"
          ? "A new opportunity."
          : scenario === "Voice conversations"
            ? "A clear answer."
            : "The right information.",
    );
    await page.getByText("Read the walkthrough", { exact: true }).click();
    await expect(page.locator(".tour-transcript ol")).toBeVisible();
    await page.getByText("Read the walkthrough", { exact: true }).click();
    await page.getByRole("button", { name: "Restart walkthrough" }).click();
    await expect(timeline).toHaveValue("0");
  }
  await page.getByRole("tab", { name: "Appointment booking" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Customer support" }),
  ).toBeFocused();
  expect(errors).toEqual([]);
});

test("reduced motion does not autoplay and ambient pause stops decoration", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Reduced motion" }),
  ).toBeDisabled();
  await page.locator("#use-cases").scrollIntoViewIfNeeded();
  await expect(
    page.getByRole("button", { name: "Play walkthrough", exact: true }),
  ).toBeVisible();
  const slider = page.getByRole("slider", { name: "Walkthrough timeline" });
  await expect(slider).toHaveValue("0");
  await page.waitForTimeout(250);
  await expect(slider).toHaveValue("0");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.getByRole("button", { name: "Pause ambient motion" }).click();
  await expect(page.locator(".site")).toHaveClass(/motion-paused/);
  expect(
    await page
      .locator(".silver-core")
      .evaluate((el) => getComputedStyle(el).animationPlayState),
  ).toBe("paused");
});

for (const width of [360, 390, 768, 1024, 1440]) {
  test(`responsive layout at ${width}px has no horizontal overflow`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await page.evaluate(async () => {
      await document.fonts.ready;
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.locator("#use-cases").scrollIntoViewIfNeeded();
    await expect(page.getByRole("tablist")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (width < 650) {
      await page.getByRole("button", { name: "Open navigation" }).click();
      await expect(
        page.getByRole("navigation", { name: "Mobile navigation" }),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(
        page.getByRole("navigation", { name: "Mobile navigation" }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Open navigation" }),
      ).toBeFocused();
      await page.getByRole("button", { name: "Open navigation" }).click();
      await page
        .getByRole("navigation", { name: "Mobile navigation" })
        .getByRole("link", { name: "How it works" })
        .click();
      await expect(
        page.getByRole("navigation", { name: "Mobile navigation" }),
      ).toHaveCount(0);
    }
  });
}

test("WCAG accessibility checks on page and interactive walkthrough", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  // Reveal each section before checking contrast; hidden reveal layers are not content.
  for (const section of await page.locator("main section").all())
    await section.scrollIntoViewIfNeeded();
  await page.locator("#use-cases").scrollIntoViewIfNeeded();
  await expect(page.getByRole("tablist")).toBeVisible();
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    result.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  ).toEqual([]);
});

test("watch CTA starts the tour and scrolling away pauses playback", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "See it in action" }).click();
  await expect(
    page.getByRole("button", { name: "Pause walkthrough", exact: true }),
  ).toBeVisible();
  const slider = page.getByRole("slider", { name: "Walkthrough timeline" });
  await expect
    .poll(async () => Number(await slider.inputValue()))
    .toBeGreaterThan(10);
  await page.locator("#faq").scrollIntoViewIfNeeded();
  await expect(
    page.getByRole("button", { name: "Play walkthrough", exact: true }),
  ).toBeAttached();
  const frame = await slider.inputValue();
  await page.waitForTimeout(150);
  await expect(slider).toHaveValue(frame);
});

test("mobile page and expanded navigation pass accessibility checks", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  for (const section of await page.locator("main section").all())
    await section.scrollIntoViewIfNeeded();
  await page.getByRole("button", { name: "Open navigation" }).click();
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    result.violations.map((v) => ({
      id: v.id,
      targets: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
});
