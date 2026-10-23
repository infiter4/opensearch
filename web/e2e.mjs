// End-to-end checks for receipts: drives the real app (vite :5173 -> backend :8000) in Chromium.
//
//   node e2e.mjs [suite ...]        default: boot errors flow stop reload task mobile
//   suites: boot errors flow stop reload task mobile deep
//
// flow/stop/reload/task/deep make REAL research calls unless the backend runs with
// RESEARCH_MODE=replay (then they replay what an earlier auto/live run recorded).
// boot/errors/mobile never start a paid run: failures are simulated with page.route.
//   SHOTS=dir   where screenshots go (default ./e2e-shots)
//   BASE=url    app under test (default http://localhost:5173)
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.env.BASE ?? "http://localhost:5173";
const OUT = process.env.SHOTS ?? "./e2e-shots";
const RUN_MS = Number(process.env.RUN_TIMEOUT_MS ?? 20 * 60_000);
const LS_KEY = "receipts.threads.v1";
const SNAPSHOT = `${OUT}/threads.json`;   // a finished thread, captured by `flow`, reused by `mobile`
mkdirSync(OUT, { recursive: true });

// Against RESEARCH_MODE=replay only recorded questions answer, so E2E_REPLAY=1 asks those.
const REPLAY = process.env.E2E_REPLAY === "1";
const Q_LITE = "What are the rate limits of Ollama's web search API?";
const Q_PRO = "How much does Tavily's search API cost and what does the free tier include?";
const [Q_FIRST, M_FIRST] = REPLAY ? [Q_PRO, "pro"] : [Q_LITE, "lite"];
const [Q_FOLLOW, M_FOLLOW] = REPLAY
  ? ["Which of those plans is cheapest per credit?", process.env.E2E_FOLLOW_MODE ?? "pro"]
  : ["Is there a paid plan with higher limits?", "auto"];
const Q_TASK = "Create a folder called trip and inside it write packing.md listing three things to pack for a beach day, then list the folder.";
const Q_DEEP = "Do AI search engines cite sources accurately?";
const Q_STOP = REPLAY ? Q_DEEP : "What is the population of Reykjavik?";

let failures = 0;
const ok = (m) => console.log(`  ok    ${m}`);
const fail = (m) => { failures++; console.log(`  FAIL  ${m}`); };
const check = (cond, m) => (cond ? ok(m) : fail(m));
const shot = (page, name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });

async function open(browser, { viewport = { width: 1440, height: 900 }, threads } = {}) {
  const ctx = await browser.newContext({ viewport });
  if (threads) await ctx.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_KEY, threads]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => {
    // The workspaces probe 503s by design when no store is configured; that is the feature flag.
    if (m.type() === "error" && !(m.location()?.url ?? "").includes("/api/workspaces")) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  await page.goto(BASE, { waitUntil: "networkidle" });
  return { ctx, page, errors };
}

const last = (page) => page.getByTestId("exchange").last();
const phase = (page) => last(page).getAttribute("data-phase");

async function ask(page, q, mode) {
  await page.getByTestId(`mode-${mode}`).click();
  await page.getByTestId("composer-input").fill(q);
  await page.getByTestId("ask").click();
}

async function waitDone(page, timeout = RUN_MS) {
  await page.waitForFunction(() => {
    const xs = document.querySelectorAll('[data-testid="exchange"]');
    const p = xs[xs.length - 1]?.getAttribute("data-phase");
    return p === "done" || p === "error" || p === "interrupted";
  }, null, { timeout, polling: 1000 });
  return phase(page);
}

const stored = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) ?? "[]"), LS_KEY);

/** Append-only collections must not double when a run is replayed into the same exchange. */
function dupes(ex) {
  const out = [];
  const dup = (xs, key, what) => {
    const ks = xs.map(key);
    if (new Set(ks).size !== ks.length) out.push(`${what} ×${ks.length - new Set(ks).size}`);
  };
  dup(ex.retracted ?? [], (r) => r.sentence_id, "retracted");
  dup(ex.conflicts ?? [], (c) => JSON.stringify(c), "conflicts");
  dup(ex.artifacts ?? [], (a) => a.id, "artifacts");
  dup(ex.notes ?? [], (n) => JSON.stringify(n), "notes");
  return out;
}

// ——— suites ——————————————————————————————————————————————————————————————————————

async function boot(browser) {
  const { ctx, page, errors } = await open(browser);
  check(await page.getByTestId("empty").isVisible(), "empty state renders");
  check((await page.getByTestId("opener").count()) === 3, "three example questions offered");
  const text = (await page.locator("body").innerText()).toLowerCase();
  for (const bad of ["file a case", "the desk", "the wire", "case №", "cross-examine"])
    if (text.includes(bad)) fail(`jargon on screen: "${bad}"`);
  check(await page.getByTestId("ask").isDisabled(), "ask is disabled with an empty question");
  await page.getByTestId("composer-input").fill("x");
  check(await page.getByTestId("ask").isEnabled(), "ask enables once there is a question");
  await page.getByTestId("composer-input").fill("");
  for (const m of ["auto", "lite", "pro", "deep"])
    check(await page.getByTestId(`mode-${m}`).isVisible(), `mode button: ${m}`);
  check((await page.getByText("corpus", { exact: true }).count()) === 0,
    "workspace controls hidden when the store is disabled");
  await page.getByTestId("toggle-sidebar").click();
  check(!(await page.getByTestId("threads").isVisible().catch(() => false)), "sidebar hides");
  await page.getByTestId("toggle-sidebar").click();
  check(await page.getByTestId("threads").isVisible(), "sidebar comes back");
  await shot(page, "boot");
  check(!errors.length, `no console errors on boot${errors.length ? `: ${errors.join(" | ")}` : ""}`);
  await ctx.close();
}

async function errorPaths(browser) {
  // 1. the start POST fails
  {
    const { ctx, page } = await open(browser);
    await page.route("**/api/research", (r) => r.fulfill({ status: 500, body: "boom" }));
    await ask(page, "simulated failure", "lite");
    await page.waitForTimeout(800);
    check((await phase(page)) === "error", "a failed start lands in the error state");
    check((await page.getByTestId("notes").innerText().catch(() => "")).includes("500"),
      "the failure is stated in the exchange");
    check(await page.getByTestId("ask").isVisible(), "composer is usable again after a failed start");
    await ctx.close();
  }
  // 2. the server no longer knows the run (backend restarted / session expired)
  {
    const { ctx, page } = await open(browser);
    await page.route("**/api/research", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ query_id: "gone0000" }) }));
    await ask(page, "simulated lost run", "lite");
    await page.waitForTimeout(6000);
    const p = await phase(page);
    check(p === "error" || p === "interrupted", `a run the server lost does not spin forever (phase=${p})`);
    check(await page.getByTestId("ask").isVisible(), "composer is not wedged by a lost run");
    await shot(page, "error-lost-run");
    await ctx.close();
  }
  // 3. a stored, interrupted exchange that never got a server id
  {
    const t = [{ id: "tx", title: "orphan", created: Date.now(), updated: Date.now(), exchanges: [{
      key: "xorphan", queryId: null, question: "orphaned question", mode: "lite", cacheMode: "auto",
      phase: "interrupted", startedAt: Date.now(), elapsed: 0, researchers: {}, order: [], sources: {},
      checks: {}, draft: {}, repairing: [], healed: [], log: [], claimsBy: {}, lastAt: Date.now(),
      ledger: { rows: [], cols: [] }, answer: { text: "", sentences: [] }, gaps: [], conflicts: [],
      retracted: [], trust: null, notes: [], graph: null, artifacts: [] }] }];
    const { ctx, page } = await open(browser, { threads: JSON.stringify(t) });
    check(await page.getByTestId("resume").isVisible(), "an interrupted exchange offers resume");
    check(await page.getByTestId("ask").isVisible(), "an interrupted exchange does not lock the composer");
    await ctx.close();
  }
  // 4. a corrupt store must not white-screen the app
  {
    const { ctx, page, errors } = await open(browser, { threads: "{not json" });
    check(await page.getByTestId("empty").isVisible(), "a corrupt store boots to the empty state");
    check(!errors.some((e) => e.startsWith("pageerror")), "no uncaught errors from a corrupt store");
    await ctx.close();
  }
}

async function flow(browser) {
  const { ctx, page, errors } = await open(browser);
  await ask(page, Q_FIRST, M_FIRST);
  await page.waitForTimeout(1500);
  check(await page.getByTestId("stop").isVisible(), "stop appears while a run is in flight");
  check(await page.getByTestId("activity").isVisible(), "the activity log shows while running");
  check(await page.getByTestId("progress").isVisible(), "the progress panel shows while running");
  await page.waitForTimeout(8000);
  check((await page.getByTestId("log-row").count()) > 2, "activity log fills in as the run proceeds");
  await shot(page, "flow-1-running");

  const t0 = Date.now();
  const p = await waitDone(page);
  check(p === "done", `${M_FIRST} run finishes (phase=${p}, ${Math.round((Date.now() - t0) / 1000)}s)`);
  const tally = await page.getByTestId("tally").innerText().catch(() => "");
  check(/\d+ of \d+ sentences verified/.test(tally), `tally is stated: "${tally}"`);
  check(await page.getByTestId("summary").isVisible(), "verification summary panel renders");
  check(await page.getByTestId("ask").isVisible(), "composer returns to ask after the run");
  await shot(page, "flow-2-answer");

  // citations open the source, with the quote located inside it
  const cites = page.locator(".cite");
  const nCites = await cites.count();
  check(nCites > 0, `answer carries citation chips (${nCites})`);
  if (nCites) {
    await cites.first().click();
    await page.getByTestId("drawer").waitFor({ timeout: 5000 });
    await page.waitForFunction(() => !document.querySelector('[data-testid="drawer"]')?.textContent?.includes("loading source"),
      null, { timeout: 30000 }).catch(() => {});
    const body = await page.getByTestId("drawer").innerText();
    check(!body.includes("could not load"), "source drawer loads the page");
    check((await page.locator('[data-testid="drawer"] mark').count()) > 0 || !body.includes("matched quote"),
      "a matched quote is highlighted when there is one");
    await shot(page, "flow-3-drawer");
    await page.keyboard.press("Escape");
    check(!(await page.getByTestId("drawer").isVisible().catch(() => false)), "Escape closes the drawer");
    await cites.first().click();
    await page.getByTestId("drawer-overlay").click({ position: { x: 20, y: 20 } });
    check(!(await page.getByTestId("drawer").isVisible().catch(() => false)), "clicking outside closes the drawer");
  }

  // the matrix
  await page.getByTestId("toggle-matrix").click();
  check(await page.getByTestId("matrix").isVisible().catch(() => false), "verification matrix opens");
  const cells = await page.getByTestId("matrix-cell").count();
  check(cells > 0, `matrix has verdict cells (${cells})`);
  if (cells) {
    await page.getByTestId("matrix-cell").first().click();
    check(await page.getByTestId("drawer").isVisible(), "a matrix cell opens its source");
    await page.getByTestId("drawer-close").click();
  }

  // the full log, with an expandable row
  await page.getByTestId("toggle-log").click();
  const rows = await page.getByTestId("log-row").count();
  check(rows > 5, `full activity log lists the run (${rows} rows)`);
  const expandable = page.getByTestId("log-row").filter({ hasText: "▸" }).first();
  if (await expandable.count()) {
    const before = await page.locator("article").last().innerText();
    await expandable.click();
    const after = await page.locator("article").last().innerText();
    check(after.length > before.length, "an expandable log row opens its detail");
  }

  // first draft <-> final
  const toggle = page.getByTestId("draft-toggle");
  if (await toggle.count()) {
    await toggle.click();
    check((await page.getByTestId("tally").innerText()).includes("first draft"), "first-draft view rewinds the tally");
    await toggle.click();
    check(/sentences verified/.test(await page.getByTestId("tally").innerText()), "final view comes back");
  } else fail("first-draft toggle missing");

  // flowchart + knowledge graph (one model call, fetched on demand)
  await page.getByTestId("toggle-flow").click();
  await page.waitForFunction(() => {
    const a = document.querySelectorAll('[data-testid="exchange"]');
    const t = a[a.length - 1].textContent ?? "";
    return document.querySelector('[data-testid="flowchart"] svg') || /could not build the chart|nothing to chart/.test(t);
  }, null, { timeout: 180000 }).catch(() => {});
  check((await page.locator('[data-testid="flowchart"] svg').count()) > 0, "flowchart draws the answer");
  await page.getByTestId("toggle-graph").click();
  await page.waitForSelector('[data-testid="graph3d"] canvas', { timeout: 120000 }).catch(() => {});
  check((await page.locator('[data-testid="graph3d"] canvas').count()) > 0, "3D knowledge graph renders");
  await page.waitForTimeout(3000);
  await shot(page, "flow-4-views");

  // the thread, a follow-up, persistence
  check((await page.getByTestId("thread").count()) === 1, "the question is filed as a thread");
  await ask(page, Q_FOLLOW, M_FOLLOW);
  const p2 = await waitDone(page);
  check(p2 === "done", `follow-up in the same thread finishes (phase=${p2})`);
  check((await page.getByTestId("exchange").count()) === 2, "the follow-up joins the open thread");
  const label = await last(page).locator(".label").first().innerText();
  check(/lite|pro|deep|task/i.test(label), `auto mode resolves to a concrete depth ("${label.split("\n")[0]}")`);
  check(/2 questions/i.test(await page.getByTestId("thread").first().innerText()), "sidebar counts the questions");

  await page.reload({ waitUntil: "networkidle" });
  check((await page.getByTestId("exchange").count()) === 2, "both exchanges survive a reload");
  check((await phase(page)) === "done", "a finished run is still finished after reload");
  check(/sentences verified/.test(await page.getByTestId("tally").first().innerText().catch(() => "")),
    "the tally survives a reload");
  writeFileSync(SNAPSHOT, await page.evaluate((k) => localStorage.getItem(k), LS_KEY));

  await page.getByTestId("new-thread").click();
  check(await page.getByTestId("empty").isVisible(), "new question opens a blank page");
  await page.getByTestId("thread").first().click();
  check((await page.getByTestId("exchange").count()) === 2, "reopening the thread restores it");

  await page.getByTestId("thread").first().hover();
  await page.getByTestId("thread-delete").first().click();
  check((await page.getByTestId("thread").count()) === 0, "deleting the thread removes it");
  await page.reload({ waitUntil: "networkidle" });
  check((await page.getByTestId("thread").count()) === 0, "a deleted thread stays deleted after reload");
  check(!errors.length, `no console errors during the flow${errors.length ? `: ${errors.slice(0, 3).join(" | ")}` : ""}`);
  await ctx.close();
}

async function stop(browser) {
  const { ctx, page } = await open(browser);
  await ask(page, Q_STOP, REPLAY ? "deep" : "lite");
  await page.waitForTimeout(4000);
  await page.getByTestId("stop").click();
  await page.waitForTimeout(1500);
  check(await page.getByTestId("ask").isVisible(), "stop hands the composer back");
  const p = await phase(page);
  check(p === "done" || p === "error", `a stopped run comes to rest (phase=${p})`);
  await page.waitForTimeout(6000);
  check((await phase(page)) === p, "a stopped run does not start moving again");
  await ctx.close();
}

async function reload(browser) {
  const { ctx, page } = await open(browser);
  await ask(page, Q_PRO, "pro");
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="log-row"]').length > 12,
    null, { timeout: 300000 });
  // Not "networkidle": a re-attached run holds its event stream open, so the network never idles.
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  const p = await phase(page);
  check(p !== "interrupted" && p !== "error", `a reload mid-run reattaches (phase=${p})`);
  const fin = await waitDone(page);
  check(fin === "done", `the reattached run finishes (phase=${fin})`);
  const [t] = await stored(page);
  const ex = t?.exchanges?.at(-1);
  const d = ex ? dupes(ex) : ["no exchange stored"];
  check(!d.length, `replaying into the exchange duplicates nothing${d.length ? `: ${d.join(", ")}` : ""}`);
  const text = await last(page).innerText();
  const first = ex?.answer?.text?.slice(0, 60);
  check(!first || text.split(first).length - 1 <= 1, "the answer text appears once, not twice");
  await shot(page, "reload-done");
  await ctx.close();
}

async function task(browser) {
  const { ctx, page } = await open(browser);
  await ask(page, Q_TASK, "auto");
  await page.waitForTimeout(20000);
  check((await last(page).getAttribute("data-kind")) === "task", "the router sends a do-this request to the task lane");
  const p = await waitDone(page);
  check(p === "done", `the task finishes (phase=${p})`);
  // A failure must not pass as a finished task: an error note means it did not do the work.
  const notes = await last(page).getByTestId("notes").innerText().catch(() => "");
  check(!notes, `the task ran without errors${notes ? `: ${notes.slice(0, 120)}` : ""}`);
  check((await last(page).innerText()).length > 120, "the task reports what it did");
  await shot(page, "task-done");
  await ctx.close();
}

async function mobile(browser) {
  const threads = existsSync(SNAPSHOT) ? readFileSync(SNAPSHOT, "utf8") : undefined;
  for (const [w, h] of [[375, 812], [768, 1024]]) {
    const { ctx, page, errors } = await open(browser, { viewport: { width: w, height: h } });
    let over = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    check(over <= 0, `${w}px: empty state has no sideways scroll (${over}px over)`);
    check(await page.getByTestId("composer-input").isVisible(), `${w}px: composer is reachable`);
    await shot(page, `mobile-${w}-empty`);
    if (threads) {
      await page.evaluate(([k, v]) => localStorage.setItem(k, v), [LS_KEY, threads]);
      await page.reload({ waitUntil: "networkidle" });
      if (await page.getByTestId("thread").count()) await page.getByTestId("thread").first().click().catch(() => {});
      over = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      check(over <= 0, `${w}px: an answer has no sideways scroll (${over}px over)`);
      await shot(page, `mobile-${w}-answer`);
    }
    check(!errors.length, `${w}px: no console errors`);
    await ctx.close();
  }
}

async function deep(browser) {
  const { ctx, page } = await open(browser);
  await ask(page, Q_DEEP, "deep");
  const p = await waitDone(page, 90 * 60_000);
  check(p === "done", `deep run finishes (phase=${p})`);
  check(/sentences verified/.test(await page.getByTestId("tally").innerText().catch(() => "")), "deep tally stated");
  check((await page.getByTestId("artifact").count()) > 0, "deep mode publishes the audit report");
  await shot(page, "deep-done");
  await ctx.close();
}

const SUITES = { boot, errors: errorPaths, flow, stop, reload, task, mobile, deep };
const pick = process.argv.slice(2);
const run = pick.length ? pick : ["boot", "errors", "flow", "stop", "reload", "task", "mobile"];

const browser = await chromium.launch();
for (const name of run) {
  console.log(`\n▸ ${name}`);
  try { await SUITES[name](browser); } catch (e) { fail(`${name} crashed: ${String(e?.message ?? e).split("\n")[0]}`); }
}
await browser.close();
console.log(failures ? `\n${failures} check(s) failed` : "\nall checks passed");
process.exitCode = failures ? 1 : 0;
