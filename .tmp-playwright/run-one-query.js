const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const query = process.argv[2];
const label = process.argv[3] || 'single';
if (!query) {
  console.error('Usage: node run-one-query.js "<query>" <label>');
  process.exit(1);
}

(async () => {
  const outputDir = path.resolve('.tmp-playwright');
  fs.mkdirSync(outputDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 } });
  page.setDefaultTimeout(180000);

  await page.goto('http://127.0.0.1:3000', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('textarea[placeholder="Ask a Customer Insights Analyst a question..."]');
  const starterButton = page.getByRole('button', { name: query, exact: true });
  if ((await starterButton.count()) > 0) {
    await starterButton.first().click();
  } else {
    const composer = page.locator('textarea[placeholder="Ask a Customer Insights Analyst a question..."]');
    await composer.click();
    await composer.type(query, { delay: 8 });
  }
  try {
    await page.waitForFunction(() => {
      const send = document.querySelector("form button[type='submit']");
      return Boolean(send) && !send.disabled;
    }, null, { timeout: 30000 });
  } catch (error) {
    const debugState = await page.evaluate(() => {
      const input = document.querySelector('textarea[placeholder="Ask a Customer Insights Analyst a question..."]');
      const send = document.querySelector("form button[type='submit']");
      return {
        inputValue: input && "value" in input ? input.value : null,
        sendText: send?.textContent?.trim() ?? null,
        sendDisabled: send ? send.disabled : null,
      };
    });
    throw new Error(`Send button never enabled: ${JSON.stringify(debugState)} :: ${String(error)}`);
  }
  await page.locator("form button[type='submit']").click();

  const assistantArticles = page.locator('article:has-text("Agent Response")');
  const currentArticle = assistantArticles.nth(1);
  await currentArticle.waitFor({ state: 'visible' });

  let completed = false;
  try {
    await page.waitForFunction(
      () => {
        const articles = Array.from(document.querySelectorAll('article')).filter((article) => article.textContent?.includes('Agent Response'));
        if (articles.length < 2) return false;
        const text = (articles[1].textContent || '').replace(/\s+/g, ' ').trim();
        return text.includes('Why It Matters') || text.includes('Request Failed');
      },
      null,
      { timeout: 180000 },
    );
    completed = true;
  } catch {
    completed = false;
  }

  const articleText = (await currentArticle.innerText()).replace(/\n{3,}/g, '\n\n').trim();
  const status = await page.evaluate(() => {
    const articles = Array.from(document.querySelectorAll('article')).filter((article) => article.textContent?.includes('Agent Response'));
    const text = (articles[1]?.textContent || '').replace(/\s+/g, ' ').trim();
    return {
      hasWhyItMatters: text.includes('Why It Matters'),
      hasRequestFailed: text.includes('Request Failed'),
      hasRunning: text.includes('Running your analysis'),
      hasSqlGenerationFailed: text.includes('SQL generation failed'),
      length: text.length,
    };
  });

  const screenshotPath = path.join(outputDir, `single-${label}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const result = { query, completed, status, articleText, screenshotPath, capturedAt: new Date().toISOString() };
  const resultPath = path.join(outputDir, `single-${label}.json`);
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2));

  console.log(JSON.stringify({ resultPath, screenshotPath, completed, status }, null, 2));

  await browser.close();
})();
