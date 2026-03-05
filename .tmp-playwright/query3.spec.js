const { test } = require('@playwright/test');
const fs = require('node:fs');

const QUERY = 'Show me new vs repeat customers by month for the last 6 months.';
const OUT_DIR = '/Users/joe/Code/ci_analyst/test-results';

function parseNdjson(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return { type: 'parse_error', line };
      }
    });
}

function extractMonthsFromResponse(response) {
  const datePattern = /^(\d{4})-(\d{2})-(\d{2})$/;
  const months = new Set();
  const tables = Array.isArray(response?.dataTables) ? response.dataTables : [];
  for (const table of tables) {
    const rows = Array.isArray(table?.rows) ? table.rows : [];
    for (const row of rows) {
      if (!row || typeof row !== 'object') continue;
      for (const value of Object.values(row)) {
        if (typeof value !== 'string') continue;
        const m = value.match(datePattern);
        if (!m) continue;
        months.add(`${m[1]}-${m[2]}`);
      }
    }
  }
  return Array.from(months).sort();
}

test('query3 replay and evidence capture', async ({ page }) => {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  await page.goto('http://127.0.0.1:3000', { waitUntil: 'domcontentloaded' });

  const starterButton = page.getByRole('button', { name: QUERY });
  if (!(await starterButton.isVisible().catch(() => false))) {
    const expand = page.getByRole('button', { name: 'Expand' });
    if (await expand.isVisible().catch(() => false)) {
      await expand.click();
    }
  }

  await starterButton.click();

  const streamResponsePromise = page.waitForResponse(
    (resp) => resp.url().includes('/api/chat/stream') && resp.request().method() === 'POST',
    { timeout: 180000 },
  );

  await page.getByRole('button', { name: 'Send' }).click();

  const streamResp = await streamResponsePromise;
  const streamPayload = await streamResp.text();

  await page.waitForFunction(() => {
    const btn = Array.from(document.querySelectorAll('button')).find((el) => el.textContent?.trim() === 'Send');
    return Boolean(btn && !btn.hasAttribute('disabled'));
  }, null, { timeout: 180000 });

  const events = parseNdjson(streamPayload);
  const responseEvents = events.filter((e) => e?.type === 'response');
  const finalEvent =
    responseEvents.find((e) => e.phase === 'final') ??
    responseEvents[responseEvents.length - 1] ??
    null;
  const finalResponse = finalEvent?.response ?? null;
  const months = extractMonthsFromResponse(finalResponse);

  const bodyText = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
  const result = {
    status: finalResponse ? 'ok' : 'no_final_response',
    query: QUERY,
    requestFailedVisible: /Request Failed/i.test(bodyText),
    hasMay2025Label: /May\s+2025/.test(bodyText),
    hasJun2025Label: /Jun\s+2025|June\s+2025/.test(bodyText),
    monthsFromDataTables: months,
    monthCount: months.length,
    firstMonth: months[0] ?? null,
    lastMonth: months[months.length - 1] ?? null,
    answerSnippet: typeof finalResponse?.answer === 'string' ? finalResponse.answer.slice(0, 220) : null,
  };

  fs.writeFileSync(`${OUT_DIR}/playwright-query3-stream.ndjson`, streamPayload, 'utf8');
  fs.writeFileSync(`${OUT_DIR}/playwright-query3-result.json`, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  await page.screenshot({ path: `${OUT_DIR}/playwright-query3.png`, fullPage: true });

  console.log(JSON.stringify(result, null, 2));
});
