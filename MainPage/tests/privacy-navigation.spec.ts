import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const key = 'phirmy:privacy-choice:v1';

test('privacy notice is honest, saves only a local preference, and can be reopened and reset', async ({page, context}) => {
  await page.goto('/');
  const notice=page.getByRole('complementary',{name:'A little note on privacy.'});
  await expect(notice).toContainText('No analytics or advertising cookies');
  expect(await page.evaluate(()=>localStorage.length)).toBe(0);
  expect(await context.cookies()).toEqual([]);
  await notice.getByRole('button',{name:'Manage',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Privacy, kept simple.'});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText('Not used',{exact:true})).toHaveCount(2);
  expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(notice.getByRole('button',{name:'Manage',exact:true})).toBeFocused();
  await notice.getByRole('button',{name:'Got it',exact:true}).click();
  await expect(notice).toHaveCount(0);
  const stored=JSON.parse((await page.evaluate(k=>localStorage.getItem(k),key))!);
  expect(stored).toMatchObject({version:1,necessaryOnly:true});
  expect(stored.expires-Date.now()).toBeGreaterThan(179*86400000);
  await page.reload(); await expect(notice).toHaveCount(0);
  await page.getByRole('button',{name:'Cookie settings',exact:true}).click();
  await dialog.getByRole('button',{name:'Reset saved choice'}).click();
  await expect(notice).toBeVisible();
  expect(await page.evaluate(k=>localStorage.getItem(k),key)).toBeNull();
});

test('cookie policy and privacy links are real pages, with no broken dashboard claims',async({page})=>{
  await page.goto('/legal/cookies');
  await expect(page.getByRole('heading',{level:1})).toHaveText('Cookie policy');
  await expect(page.locator('main')).toContainText(key);
  await expect(page.locator('main')).toContainText('180 days');
  await page.locator('main').getByRole('button',{name:'Cookie settings'}).click();
  await page.getByRole('button',{name:'Save preferences'}).click();
  await page.goto('/legal/privacy');
  await expect(page.getByRole('heading',{level:1})).toHaveText('Privacy notice');
  await page.goto('/legal/terms');
  await expect(page.getByRole('heading',{level:1})).toHaveText('Website terms');
  await page.getByRole('link',{name:'Back to Phirmy'}).click();
  await expect(page.getByRole('link',{name:'Request workspace access'})).toHaveAttribute('href','/contact');
  await expect(page.getByRole('link',{name:'Log in',exact:true})).toHaveCount(0);
});

test('expired choices and unavailable storage remain usable without enabling tracking',async({page})=>{
  await page.addInitScript(k=>localStorage.setItem(k,JSON.stringify({version:1,necessaryOnly:true,expires:1})),key);
  await page.goto('/');
  await expect(page.getByRole('button',{name:'Got it',exact:true})).toBeVisible();
  await page.evaluate(()=>{ Storage.prototype.setItem=()=>{throw new DOMException('blocked','SecurityError');}; });
  await page.getByRole('button',{name:'Got it',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('could not save');
  await expect(page.getByRole('link',{name:'Build your agent',exact:true})).toBeEnabled();
});

test('product dropdown supports keyboard, closing, and implemented feature links',async({page})=>{
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('/');
  const button=page.getByRole('button',{name:'Product',exact:true});
  await button.focus(); await page.keyboard.press('Enter');
  await expect(button).toHaveAttribute('aria-expanded','true');
  await expect(page.locator('#product-navigation')).toContainText('Website chat');
  const audit=await new AxeBuilder({page}).include('#product-navigation').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  expect(audit.violations).toEqual([]);
  await page.keyboard.press('Escape'); await expect(button).toBeFocused();
  await button.click();
  await page.locator('#product-navigation').getByRole('link',{name:'Voice conversations',exact:false}).click();
  await expect(button).toHaveAttribute('aria-expanded','false');
  await expect(page).toHaveURL(/#voice-conversations$/);
  await expect(page.getByRole('heading',{name:'A voice worth talking to.'})).toBeVisible();
});
