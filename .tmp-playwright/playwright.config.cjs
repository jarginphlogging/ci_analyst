module.exports = {
  testDir: '/Users/joe/Code/ci_analyst/.tmp-playwright',
  testMatch: /query3\.spec\.js/,
  timeout: 240000,
  outputDir: '/Users/joe/Code/ci_analyst/.tmp-playwright/output',
  use: {
    headless: true,
    viewport: { width: 1440, height: 900 },
  },
  workers: 1,
};
