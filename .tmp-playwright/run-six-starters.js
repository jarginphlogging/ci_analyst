const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const queries = [
  'Show me total sales last month.',
  'Show me sales by state in descending order.',
  'Show me new vs repeat customers by month for the last 6 months.',
  'What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?',
  'For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?',
  'What were my top and bottom performing stores for 2025, what was the new vs repeat customer mix for each one, and how does that compare to the prior period?',
];

const outputDir = path.resolve('.tmp-playwright');
const logPath = path.join(outputDir, 'run-six-starters.log');

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  fs.appendFileSync(logPath, `${line}\n`);
  console.log(line);
}

async function runSingleQuery(browser, query, index) {
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 } });
  page.setDefaultTimeout(180000);

  await page.goto('http://127.0.0.1:3000', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('textarea[placeholder="Ask a Customer Insights Analyst a question..."]');

  await page.fill('textarea[placeholder="Ask a Customer Insights Analyst a question..."]', query);
  await page.waitForFunction(() => {
    const send = document.querySelector("form button[type='submit']");
    return Boolean(send) && !send.disabled;
  });

  await page.locator("form button[type='submit']").click();

  const assistantArticles = page.locator('article:has-text("Agent Response")');
  const currentArticle = assistantArticles.nth(1);
  await currentArticle.waitFor({ state: 'visible', timeout: 180000 });

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

  const articleText = (await currentArticle.innerText()).replace(/\n{3,}/g, '\n\n').trim();
  const screenshotPath = path.join(outputDir, `starter-query-${index + 1}.png`);
  await currentArticle.scrollIntoViewIfNeeded();
  await page.screenshot({ path: screenshotPath, fullPage: true });

  await page.close();

  return {
    index: index + 1,
    query,
    articleText,
    screenshotPath,
  };
}

async function run() {
  fs.mkdirSync(outputDir, { recursive: true });
  fs.writeFileSync(logPath, '');
  log('Starting run');

  const browser = await chromium.launch({ headless: true });
  const results = [];

  for (let i = 0; i < queries.length; i += 1) {
    const query = queries[i];
    log(`Running query ${i + 1}/6: ${query}`);
    try {
      const result = await runSingleQuery(browser, query, i);
      results.push(result);
      log(`Completed query ${i + 1}/6`);
    } catch (error) {
      log(`Query ${i + 1}/6 failed: ${error.stack || error}`);
      results.push({
        index: i + 1,
        query,
        error: String(error),
      });
    }
  }

  const outputPath = path.join(outputDir, 'starter-query-results.json');
  fs.writeFileSync(outputPath, JSON.stringify({ generatedAt: new Date().toISOString(), results }, null, 2));
  log(`Saved results to ${outputPath}`);

  await browser.close();
  log('Browser closed');
}

run().catch((error) => {
  log(`Run failed: ${error.stack || error}`);
  process.exit(1);
});
