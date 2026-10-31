import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
const narration = JSON.parse(readFileSync(new URL('../src/motion/narration-manifest.json', import.meta.url), 'utf8'));

test('narration follows play, pause, seek and scenario changes with readable captions', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => {
    const state = {starts: 0, decoded: false, running: false};
    (window as any).__audioEvidence = state;
    const create = AudioContext.prototype.createBufferSource;
    AudioContext.prototype.createBufferSource = function () {
      const source = create.call(this);
      const start = source.start.bind(source);
      source.start = (...args: Parameters<typeof source.start>) => {
        state.starts++;
        state.decoded ||= Boolean(source.buffer && source.buffer.duration > 0);
        state.running ||= this.state === 'running';
        start(...args);
      };
      return source;
    };
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'See it in action' }).click();
  await expect.poll(() => page.evaluate(() => {const a=(window as any).__audioEvidence;return a.starts>0 && a.decoded && a.running;})).toBe(true);
  await page.getByRole('button', { name: 'Mute narration', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Unmute narration' })).toBeVisible();
  await page.getByRole('button', { name: 'Pause walkthrough' }).click();
  const stopped = await page.getByRole('slider', {name:'Walkthrough timeline'}).inputValue();
  await page.waitForTimeout(150);
  await expect(page.getByRole('slider', {name:'Walkthrough timeline'})).toHaveValue(stopped);
  await page.getByRole('slider', { name: 'Walkthrough timeline' }).fill(String(narration.support.clips[1].from + 30));
  await expect(page.locator('.spoken-caption')).toContainText('Give clear answers');
  await page.getByRole('tab', { name: 'Voice conversations', exact: true }).click();
  await expect(page.locator('.spoken-caption')).toContainText('Let people speak');
  await page.getByRole('button', { name: 'Unmute narration' }).click();
  const starts = await page.evaluate(() => (window as any).__audioEvidence.starts);
  await page.getByRole('button', { name: 'Play walkthrough', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__audioEvidence.starts)).toBeGreaterThan(starts);
  expect(errors).toEqual([]);
});
