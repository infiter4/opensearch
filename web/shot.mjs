// Screenshot driver for the newsroom UI. Usage:
//   node shot.mjs empty            -> empty state
//   node shot.mjs run [mode]       -> file a case, screenshot the wire, the galley, the grid
import { chromium } from "playwright";

const OUT = "/tmp/claude-1000/-home-demo/738797a0-b5f0-4876-9081-c81d3dd90924/scratchpad";
const mode = process.argv[2] ?? "empty";
const runMode = process.argv[3] ?? "pro";

const QUESTIONS = {
  lite: "What are the rate limits of Ollama's web search API?",
  pro: "How much does Tavily's search API cost and what does the free tier include?",
  deep: "Do AI search engines cite sources accurately?",
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

// A silent console error is how a broken UI screenshots as a pretty one. Collect, then report.
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(`CONSOLE: ${m.text()}`); });
page.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message}`));

await page.goto("http://localhost:5173", { waitUntil: "networkidle" });

if (mode === "empty") {
  await page.screenshot({ path: `${OUT}/ui-empty.png` });
  console.log("saved ui-empty.png");
}

if (mode === "run") {
  await page.fill("textarea", QUESTIONS[runMode]);
  await page.locator("footer button").filter({ hasText: new RegExp(`^${runMode}$`) }).click();
  await page.locator("footer button").filter({ hasText: /^ask/ }).click();

  await page.waitForTimeout(5000);
  await page.screenshot({ path: `${OUT}/ui-wire.png` });
  console.log("saved ui-wire.png (the wire, live)");

  await page.waitForSelector("text=sentences verified", { timeout: 900000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${OUT}/ui-answer.png`, fullPage: true });
  console.log("saved ui-answer.png");

  // the first-draft rewind — the pitch gesture
  await page.locator("button").filter({ hasText: /^final$/ }).click();
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/ui-draft.png`, fullPage: true });
  console.log("saved ui-draft.png (rewound to the first draft)");
  await page.locator("button").filter({ hasText: /^first draft$/ }).click();
  await page.waitForTimeout(400);

  await page.locator("button").filter({ hasText: /verification matrix/ }).click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/ui-grid.png`, fullPage: true });
  console.log("saved ui-grid.png");

  for (const [label, rx] of [["provenance", /provenance/], ["flow", /how this was researched/]]) {
    const b = page.locator("button").filter({ hasText: rx });
    if (await b.count()) {
      await b.click();
      await page.waitForTimeout(1800);
      await page.screenshot({ path: `${OUT}/ui-${label}.png`, fullPage: true });
      console.log(`saved ui-${label}.png`);
    }
  }

  // a citation chip must open the drawer on the exact quote
  const chip = page.locator("button.cite").first();
  if (await chip.count()) {
    await chip.click();
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${OUT}/ui-source.png` });
    console.log("saved ui-source.png (source drawer)");
  } else {
    console.log("NO CITATION CHIP FOUND");
  }
}

console.log(errors.length ? `\n${errors.length} ERRORS:\n${errors.join("\n")}` : "\nno console errors");
await browser.close();
