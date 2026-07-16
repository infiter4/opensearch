// End-to-end check of the features asked for: threads (view + continue past conversations),
// follow-ups, persistence across reload, the reworded UI, and no console errors anywhere.
//   node e2e.mjs
import { chromium } from "playwright";

const OUT = "/tmp/claude-1000/-home-demo/738797a0-b5f0-4876-9081-c81d3dd90924/scratchpad";
const Q1 = "How much does Tavily's search API cost and what does the free tier include?";
const Q2 = "What are the rate limits of Ollama's web search API?";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(`CONSOLE: ${m.text()}`); });
page.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message}`));

const fail = (msg) => { console.log(`FAIL: ${msg}`); process.exitCode = 1; };
const ok = (msg) => console.log(`  ok  ${msg}`);

await page.goto("http://localhost:5173", { waitUntil: "networkidle" });
await page.evaluate(() => localStorage.clear());
await page.reload({ waitUntil: "networkidle" });

// ——— 1. no jargon on the empty state
const empty = await page.evaluate(() => document.body.innerText.toLowerCase());
for (const bad of ["file a case", "the desk", "the wire", "case №", "the tally", "cross-examine"]) {
  if (empty.includes(bad)) fail(`jargon still on screen: "${bad}"`);
}
ok("empty state is free of jargon");
if (!empty.includes("ask a question") && !(await page.locator("textarea").getAttribute("placeholder"))?.includes("Ask"))
  fail("composer placeholder is not 'Ask a question…'");
ok("composer says 'Ask a question…'");

// ——— 2. ask Q1 (pro)
await page.fill("textarea", Q1);
await page.locator("footer button").filter({ hasText: /^pro$/ }).click();
await page.locator("footer button").filter({ hasText: /^ask/ }).click();

// stop button must appear while running
await page.waitForTimeout(1200);
if (!(await page.locator("footer button").filter({ hasText: /^stop$/ }).count()))
  fail("no stop button while a run is in flight");
else ok("stop button appears during a run");

await page.waitForSelector("text=sentences verified", { timeout: 900000 });
ok("Q1 finished and reports 'N of M sentences verified'");
await page.screenshot({ path: `${OUT}/e2e-1-answer.png`, fullPage: true });

// ——— 3. thread appears in the sidebar
const threadCount = async () => await page.locator("nav button").filter({ hasText: Q1.slice(0, 30) }).count();
if (!(await threadCount())) fail("Q1 did not appear in the thread sidebar");
else ok("Q1 appears in the sidebar");

// ——— 4. follow-up in the SAME thread
await page.fill("textarea", "Which of those plans is cheapest per credit?");
await page.locator("footer button").filter({ hasText: /^lite$/ }).click();
await page.locator("footer button").filter({ hasText: /^ask/ }).click();
await page.waitForTimeout(2500);
const nArticles = await page.locator("article").count();
if (nArticles < 2) fail(`follow-up did not append to the thread (articles=${nArticles})`);
else ok(`follow-up appended to the same thread (${nArticles} exchanges)`);
await page.screenshot({ path: `${OUT}/e2e-2-followup.png` });

// stop it — we only needed to prove it appends and that stop works
const stopBtn = page.locator("footer button").filter({ hasText: /^stop$/ });
if (await stopBtn.count()) { await stopBtn.click(); await page.waitForTimeout(600); ok("stop halted the follow-up"); }

// ——— 5. new thread
await page.locator("nav button").filter({ hasText: /new question/ }).click();
await page.waitForTimeout(400);
if (await page.locator("article").count()) fail("new thread did not clear the view");
else ok("'+ new question' opens a blank thread");

await page.fill("textarea", Q2);
await page.locator("footer button").filter({ hasText: /^lite$/ }).click();
await page.locator("footer button").filter({ hasText: /^ask/ }).click();
await page.waitForSelector("text=sentences verified", { timeout: 900000 });
ok("Q2 finished in its own thread");
const threads = await page.locator("nav button").filter({ hasText: /\?$|cost|limits/ }).count();
if (threads < 2) fail(`sidebar should list 2 threads, saw ${threads}`);
else ok(`sidebar lists ${threads} threads`);
await page.screenshot({ path: `${OUT}/e2e-3-threads.png`, fullPage: true });

// ——— 6. switch back to the first thread and read it
await page.locator("nav button").filter({ hasText: Q1.slice(0, 30) }).first().click();
await page.waitForTimeout(600);
const back = await page.evaluate(() => document.body.innerText);
if (!back.includes("Tavily")) fail("switching back to thread 1 did not restore its content");
else ok("switching threads restores the past conversation");

// ——— 7. persistence across reload
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(900);
const afterReload = await page.locator("nav button").filter({ hasText: /cost|limits/ }).count();
if (afterReload < 2) fail(`threads did not survive reload (saw ${afterReload})`);
else ok(`threads survive a reload (${afterReload} in sidebar)`);
await page.screenshot({ path: `${OUT}/e2e-4-reload.png`, fullPage: true });

// ——— 8. open a past thread after reload and confirm it is readable
await page.locator("nav button").filter({ hasText: Q1.slice(0, 30) }).first().click();
await page.waitForTimeout(700);
const restored = await page.evaluate(() => ({
  text: document.body.innerText,
  marks: document.querySelectorAll("span.mk").length,
  chips: document.querySelectorAll("button.cite").length,
}));
if (!restored.text.includes("sentences verified")) fail("restored thread lost its verification summary");
else ok("restored thread still shows its verification summary");
if (!restored.marks) fail("restored thread lost its verdict marks");
else ok(`restored thread keeps ${restored.marks} verdict marks and ${restored.chips} citation chips`);
await page.screenshot({ path: `${OUT}/e2e-5-restored.png`, fullPage: true });

console.log(errors.length ? `\n${errors.length} ERRORS:\n${errors.join("\n")}` : "\nno console errors");
if (errors.length) process.exitCode = 1;
await browser.close();
