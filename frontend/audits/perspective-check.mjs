import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport:{width:1600,height:1000}, reducedMotion:'reduce'});
page.on('pageerror', e => console.log('PAGE ERROR',e.message));
for (const width of [1600,390,320]) {
 await page.setViewportSize({width,height:1000});
 await page.goto('http://127.0.0.1:3000',{waitUntil:'networkidle',timeout:120000});
 await page.screenshot({path:`audits/out-perspective-${width}.png`});
 await page.locator('.hero-stage').screenshot({path:`audits/out-perspective-stage-${width}.png`});
 console.log(await page.evaluate(()=>({width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,heroBackground:getComputedStyle(document.querySelector('#top')).backgroundColor,heroOverflow:getComputedStyle(document.querySelector('#top')).overflow})));
}
await page.setViewportSize({width:1600,height:1000});
await page.goto('http://127.0.0.1:3000');
await page.getByRole('button',{name:'Switch between light and dark'}).click();
await page.screenshot({path:'audits/out-perspective-dark.png'});
await browser.close();
