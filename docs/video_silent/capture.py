import asyncio, base64, json, time, os, sys
from playwright.async_api import async_playwright
sys.path.insert(0, '.')
from script import durs
LEAD, TAIL = 0.4, 0.8
T = {k: v + LEAD + TAIL for k, v in durs().items()}
CURSOR = open('/home/claude/tbo-repo/docs/video/capture.py').read().split('CURSOR = """')[1].split('"""')[0]
class Rec:
    def __init__(self, cdp): self.cdp, self.frames, self.dir, self.t0 = cdp, [], None, 0
    async def on(self, p):
        if self.dir:
            ts = time.time() - self.t0
            path = f"{self.dir}/{len(self.frames):05d}.jpg"
            open(path, 'wb').write(base64.b64decode(p['data'])); self.frames.append((max(ts, 0), path))
        try: await self.cdp.send('Page.screencastFrameAck', {'sessionId': p['sessionId']})
        except Exception: pass
    async def start(self, sid):
        self.dir = f'frames/{sid}'; os.makedirs(self.dir, exist_ok=True); self.frames = []; self.t0 = time.time()
        await self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': 1920, 'maxHeight': 1080, 'everyNthFrame': 1})
    async def stop(self, sid):
        await self.cdp.send('Page.stopScreencast'); await asyncio.sleep(0.1); self.dir = None
        json.dump(self.frames, open(f'frames/{sid}.json', 'w'))
        print(sid, len(self.frames), 'frames, last', round(self.frames[-1][0], 2) if self.frames else None, 'target', round(T[sid], 2), flush=True)
async def at(t0, t):
    d = t0 + t - time.time()
    if d > 0: await asyncio.sleep(d)
async def center(loc):
    b = await loc.bounding_box(); return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
async def scroll_to(pg, sel_js, off=150):
    await pg.evaluate(f"(() => {{ const el = {sel_js}; if (el) window.scrollTo({{top: el.getBoundingClientRect().top + window.scrollY - {off}, behavior: 'smooth'}}) }})()")
CARD = lambda t: f"[...document.querySelectorAll('.card')].find(c => c.innerText.includes({json.dumps(t)}))"
async def nav(pg, label):
    b = pg.locator(f"nav button:has-text('{label}')"); x, y = await center(b)
    await pg.mouse.move(x, y, steps=25); await b.click(); await pg.evaluate("window.scrollTo(0,0)")
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--hide-scrollbars"])
        ctx = await b.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="light")
        await ctx.add_init_script(CURSOR)
        pg = await ctx.new_page(); cdp = await ctx.new_cdp_session(pg)
        rec = Rec(cdp); cdp.on('Page.screencastFrame', lambda prm: asyncio.ensure_future(rec.on(prm)))
        await pg.goto("http://localhost:8011/#home"); await pg.wait_for_selector('.hero'); await pg.wait_for_timeout(2500)
        await pg.mouse.move(960, 600)
        # warm up the optimizer so the first scene is not a loading spinner
        await pg.evaluate("location.hash='optimizer'"); await pg.wait_for_selector('.kpi'); await pg.wait_for_timeout(4000)
        await pg.evaluate("location.hash='home'"); await pg.wait_for_timeout(1500)

        await rec.start('s4'); t0 = time.time()
        await at(t0, 0.6); await nav(pg, 'Budget Optimizer'); await pg.wait_for_selector('.kpi')
        for t, label in [(3.0, 'Expected profit'), (7.5, "vs last year"), (11.5, 'Saved by buying early')]:
            await at(t0, t); x, y = await center(pg.locator(f".kpi:has-text(\"{label}\")").first); await pg.mouse.move(x, y, steps=30)
        await at(t0, T['s4']); await rec.stop('s4')

        await rec.start('s5'); t0 = time.time()
        inp = pg.locator('.budget-in input'); x, y = await center(inp)
        await at(t0, 0.3); await pg.mouse.move(x, y, steps=25); await inp.click(click_count=3); await pg.keyboard.type('200', delay=160)
        await at(t0, 4.0); await scroll_to(pg, CARD('of the budget is not invested'), 140)
        await at(t0, 5.5); await pg.mouse.move(1100, 420, steps=40)
        await at(t0, T['s5']); await rec.stop('s5')

        await rec.start('s6'); t0 = time.time()
        await pg.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); await at(t0, 0.6)
        rst = pg.locator("button:has-text('Reset to defaults')"); x, y = await center(rst); await pg.mouse.move(x, y, steps=20); await rst.click()
        await at(t0, 2.4); await scroll_to(pg, CARD('Buy plan'), 140)
        await at(t0, 3.6); row = pg.locator(".card:has-text('Buy plan') tbody tr").first; x, y = await center(row); await pg.mouse.move(x - 300, y, steps=25); await row.click()
        await at(t0, 7.8); await pg.evaluate("(() => { const d = document.querySelector('.drawer'); const h = [...d.querySelectorAll('h3,h4,b,strong')].find(e => /supplier/i.test(e.innerText)); if (h) d.scrollTo({top: h.offsetTop - 80, behavior: 'smooth'}); else d.scrollTo({top: d.scrollHeight, behavior:'smooth'}) })()")
        await at(t0, 9.0); await pg.mouse.move(1600, 600, steps=30)
        await at(t0, T['s6']); await rec.stop('s6')

        await rec.start('s7'); t0 = time.time()
        await at(t0, 0.3); await pg.keyboard.press('Escape'); await at(t0, 0.9); await nav(pg, 'What-if & Re-planning')
        await pg.wait_for_selector("button.chip.sm")
        await at(t0, 3.2); chip = pg.locator("button.chip.sm:has-text('Fuel surcharge')"); x, y = await center(chip); await pg.mouse.move(x, y, steps=25); await chip.click()
        await at(t0, 7.0); await pg.evaluate("window.scrollTo({top: 420, behavior: 'smooth'})"); await pg.mouse.move(1200, 560, steps=40)
        await at(t0, T['s7']); await rec.stop('s7')

        await rec.start('s8'); t0 = time.time()
        await scroll_to(pg, CARD('Automated re-planning'), 130)
        await at(t0, 1.4); btn = pg.locator("button:has-text('Start live feed')"); x, y = await center(btn); await pg.mouse.move(x, y, steps=25); await btn.click()
        await at(t0, 4.0); await pg.mouse.move(900, 760, steps=40)
        await at(t0, T['s8']); await rec.stop('s8')

        await rec.start('s9'); t0 = time.time()
        b2 = pg.locator("button:has-text('Pause feed')")
        if await b2.count(): await b2.click()
        await at(t0, 0.4); await nav(pg, 'Suppliers'); await pg.wait_for_timeout(800)
        await at(t0, 3.0); x, y = await center(pg.locator(".card:has-text('Supplier scorecard') table")); await pg.mouse.move(x, y, steps=40)
        await at(t0, 7.5); await scroll_to(pg, CARD('How a supplier is chosen'), 140)
        await at(t0, T['s9']); await rec.stop('s9')

        await rec.start('s10'); t0 = time.time()
        await at(t0, 0.4); await nav(pg, 'Accuracy & Validation'); await pg.wait_for_timeout(800)
        await at(t0, 4.5); await scroll_to(pg, CARD('Forecast error table'), 140)
        await at(t0, 9.5); await scroll_to(pg, CARD('Forecast vs actual demand'), 140)
        await at(t0, 13.5); await scroll_to(pg, CARD('would the plan have made money'), 140)
        await at(t0, 20.5); await scroll_to(pg, CARD('Mathematical verification'), 140)
        await at(t0, T['s10']); await rec.stop('s10')

        await rec.start('s11'); t0 = time.time()
        await at(t0, 0.4); await nav(pg, 'Data Sources'); await pg.wait_for_timeout(600)
        await at(t0, 6.0); await scroll_to(pg, CARD('Data contract'), 140)
        await at(t0, T['s11']); await rec.stop('s11')
        await b.close()
asyncio.run(main())
