"""Playwright DOM audit: every tab on desktop and phone width (renders, no overflow, simulated-data label, no console errors) plus accuracy metrics, file validation and what-if page.
Usage: python frontend/audit_dom.py http://localhost:8000"""
import asyncio, sys, json
from playwright.async_api import async_playwright
BASE = sys.argv[1]
TABS = ['home','optimizer','scenarios','suppliers','overview','forecasts','accuracy','risk','data']
res = []
def ok(n, c, d=''): res.append((n, bool(c), d))
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for vw, label in [((1400, 900), 'desktop'), ((390, 844), 'mobile')]:
            pg = await b.new_page(viewport={'width': vw[0], 'height': vw[1]})
            errs = []
            pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
            pg.on('pageerror', lambda e: errs.append(str(e)))
            await pg.goto(BASE + '/#home'); await pg.wait_for_timeout(2500)
            for t in TABS:
                await pg.evaluate(f"location.hash='{t}'"); await pg.wait_for_timeout(4500 if t in ('optimizer','scenarios','risk') else 2000)
                txt = await pg.inner_text('main') if await pg.locator('main').count() else await pg.inner_text('body')
                ok(f'{label} {t} renders', len(txt) > 300 and 'Loading' not in txt[:200], txt[:80].replace('\n',' '))
                ov = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                ok(f'{label} {t} no horizontal overflow', ov <= 1, f'overflow {ov}px')
                ok(f'{label} {t} has simulated label', 'simulated' in txt.lower() or 'synthetic' in txt.lower())
            ok(f'{label} no console errors', not errs, '; '.join(errs[:3]))
            await pg.close()
        # functional: optimizer unused budget, scenario, data validate
        pg = await b.new_page(viewport={'width': 1400, 'height': 900})
        await pg.goto(BASE + '/#accuracy'); await pg.wait_for_timeout(4000)
        t = await pg.inner_text('body')
        for k in ['WAPE', 'MAE', 'RMSE', '87.5%']: ok(f'accuracy shows {k}', k in t)
        await pg.goto(BASE + '/#data'); await pg.wait_for_timeout(2500)
        await pg.set_input_files('input[type=file]', files=[{'name':'items.csv','mimeType':'text/csv','buffer':b'item_id,name\nA,b\n'}])
        await pg.click('button:has-text("Check file")'); await pg.wait_for_timeout(2000)
        ok('data validate shows issues', 'missing required columns' in await pg.inner_text('body'))
        await pg.goto(BASE + '/#scenarios'); await pg.wait_for_timeout(5000)
        t = await pg.inner_text('body'); ok('scenarios page content', 'plan' in t.lower(), t[:200].replace('\n',' '))
        await pg.screenshot(path='/tmp/scen.png', full_page=False)
        await b.close()
asyncio.run(main())
f = [r for r in res if not r[1]]
print(f'{len(res)-len(f)}/{len(res)} passed')
for r in f: print('FAIL', r[0], '|', r[2])
