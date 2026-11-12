import asyncio, base64, json, time, os
from playwright.async_api import async_playwright
D = json.load(open('durs.json'))
LEAD, TAIL = 0.35, 0.65
T = {k: v + LEAD + TAIL for k, v in D.items()}
CURSOR = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.id = '__cur';
  c.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24"><path d="M3 2l7 19 2.5-7.5L20 11z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, {position:'fixed', left:'-50px', top:'-50px', zIndex: 2147483647, pointerEvents:'none', transition:'transform .08s'});
  document.documentElement.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; }, true);
  document.addEventListener('mousedown', () => c.style.transform = 'scale(.82)', true);
  document.addEventListener('mouseup', () => c.style.transform = 'scale(1)', true);
});
"""
class Rec:
    def __init__(self, cdp): self.cdp, self.frames, self.dir, self.t0 = cdp, [], None, 0
    async def on(self, p):
        if self.dir:
            ts = p['metadata']['timestamp'] - self.t0
            path = f"{self.dir}/{len(self.frames):05d}.jpg"
            open(path, 'wb').write(base64.b64decode(p['data']))
            self.frames.append((max(ts, 0), path))
        try: await self.cdp.send('Page.screencastFrameAck', {'sessionId': p['sessionId']})
        except Exception: pass
    async def start(self, sid):
        self.dir = f'frames/{sid}'; os.makedirs(self.dir, exist_ok=True); self.frames = []
        self.t0 = time.time()
        await self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': 1920, 'maxHeight': 1080, 'everyNthFrame': 1})
    async def stop(self, sid):
        await self.cdp.send('Page.stopScreencast'); await asyncio.sleep(0.1); self.dir = None
        json.dump(self.frames, open(f'frames/{sid}.json', 'w'))
        print(sid, len(self.frames), 'frames, last ts', round(self.frames[-1][0], 2) if self.frames else None, 'target', round(T[sid], 2))

async def at(t0, t):   # wait until t seconds after t0
    d = t0 + t - time.time()
    if d > 0: await asyncio.sleep(d)

async def glide(pg, x, y, steps=25):
    await pg.mouse.move(x, y, steps=steps)

async def center(loc):
    b = await loc.bounding_box(); return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--hide-scrollbars"])
        ctx = await b.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="light")
        await ctx.add_init_script(CURSOR)
        pg = await ctx.new_page()
        cdp = await ctx.new_cdp_session(pg)
        rec = Rec(cdp); cdp.on('Page.screencastFrame', lambda prm: asyncio.ensure_future(rec.on(prm)))
        await pg.goto("http://localhost:8090/#home"); await pg.wait_for_selector('.hero'); await pg.wait_for_timeout(2500)
        await pg.mouse.move(960, 600)

        # s4: open optimizer, tour the KPI tiles
        await rec.start('s4'); t0 = time.time()
        nav = pg.locator("nav button:has-text('Budget Optimizer')")
        x, y = await center(nav); await at(t0, 0.3); await glide(pg, x, y, 30); await at(t0, 1.3); await nav.click()
        await pg.wait_for_selector('.kpi')
        for t, label in [(4.2, 'Expected profit'), (7.2, "vs last year's mix"), (10.0, 'Saved by buying early')]:
            await at(t0, t); x, y = await center(pg.locator(f".kpi:has-text(\"{label}\")").first); await glide(pg, x, y, 30)
        await at(t0, T['s4']); await rec.stop('s4')

        # s5: budget to 200 Cr, look at strategy comparison
        await rec.start('s5'); t0 = time.time()
        inp = pg.locator('.budget-in input'); x, y = await center(inp)
        await at(t0, 0.2); await glide(pg, x, y, 30); await at(t0, 1.1); await inp.click(click_count=3)
        await pg.keyboard.type('200', delay=180)
        await at(t0, 3.4); x, y = await center(pg.locator(".card:has-text('Strategy comparison')")); await glide(pg, x + 210, y + 40, 40)
        await at(t0, 7.0); x, y = await center(pg.locator(".card:has-text('Profit distribution')")); await glide(pg, x, y, 40)
        await at(t0, T['s5']); await rec.stop('s5')

        # s6: reset, then drag the risk slider towards "protect downside"
        await rec.start('s6'); t0 = time.time()
        rst = pg.locator("button:has-text('Reset to defaults')"); x, y = await center(rst)
        await at(t0, 0.1); await glide(pg, x, y, 25); await at(t0, 0.9); await rst.click()
        sl = pg.locator("input[aria-label='Risk aversion lambda']"); bb = await sl.bounding_box()
        y = bb['y'] + bb['height'] / 2; x0 = bb['x'] + 9 + 0.3 * (bb['width'] - 18); x1 = bb['x'] + 9 + 0.9 * (bb['width'] - 18)
        await at(t0, 2.0); await glide(pg, x0, y, 20); await pg.mouse.down()
        await pg.mouse.move(x1, y, steps=60); await pg.mouse.up()
        await at(t0, 5.6); x, y = await center(pg.locator(".kpi:has-text('Worst-10% profit')").first); await glide(pg, x, y, 30)
        await at(t0, T['s6']); await rec.stop('s6')

        # s7: scroll to the buy plan and open an explanation
        await rec.start('s7'); t0 = time.time()
        await pg.evaluate("window.scrollTo({top: document.querySelector('.tbl-wrap').getBoundingClientRect().top + window.scrollY - 260, behavior: 'smooth'})")
        await at(t0, 1.4); row = pg.locator(".card:has-text('Buy plan') tbody tr").first; x, y = await center(row)
        await glide(pg, x - 300, y, 25); await at(t0, 2.1); await row.click()
        await at(t0, 4.3); await glide(pg, 1650, 560, 30)
        await at(t0, T['s7']); await rec.stop('s7')

        # s8: proof - back-test card then the scorecard
        await rec.start('s8'); t0 = time.time()
        await at(t0, 0.3); await pg.keyboard.press('Escape')
        nav = pg.locator("nav button:has-text('Demand & Opportunities')"); x, y = await center(nav)
        await at(t0, 0.8); await glide(pg, x, y, 30); await at(t0, 1.8); await nav.click(); await pg.wait_for_timeout(900)
        await pg.evaluate("window.scrollTo({top: document.querySelector('.card .mini-h').closest('section').getBoundingClientRect().top + window.scrollY - 90, behavior: 'smooth'})")
        await at(t0, 6.0); x, y = await center(pg.locator(".card:has-text('Back-test') table")); await glide(pg, x, y, 40)
        await at(t0, 15.0)
        await pg.evaluate("window.scrollTo({top: [...document.querySelectorAll('section.card')].find(s=>s.innerText.includes('Model accuracy scorecard')).getBoundingClientRect().top + window.scrollY - 90, behavior: 'smooth'})")
        await at(t0, 17.0); x, y = await center(pg.locator(".card:has-text('Model accuracy scorecard') tbody tr").first); await glide(pg, x + 400, y, 40)
        await at(t0, T['s8']); await rec.stop('s8')
        await b.close()
asyncio.run(main())
