import {test, expect} from '@playwright/test';

test('React Bits accents rotate, pause and respect changing reduced motion', async ({page}) => {
  await page.setViewportSize({width:1440,height:1000});
  const errors:string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  const word=page.locator('.conversation-word');
  await expect(word).toContainText('first hellos.');
  await expect(word).toContainText('bright ideas.', {timeout:7000});
  await page.getByRole('button',{name:'Pause ambient motion'}).click();
  await expect(page.locator('.conversation-word-static')).toHaveText('real connections.');
  await expect(page.locator('.hero-threads canvas')).toHaveCount(0);
  await page.getByRole('button',{name:'Resume ambient motion'}).click();
  await expect(word).toBeVisible();
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(page.locator('.conversation-word-static')).toBeVisible();
  await expect(page.locator('.hero-threads canvas')).toHaveCount(0);
  await expect(page.getByRole('heading',{level:1})).toHaveAccessibleName('Your business. Always there.');
  expect(errors).toEqual([]);
});

test('mobile retains stable readable text without a WebGL backdrop',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await expect(page.locator('.conversation-words')).toBeVisible();
  await expect(page.locator('.hero-threads canvas')).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('link',{name:'Build your agent',exact:true}).click();
  await expect(page).toHaveURL(/\/contact$/);
});
