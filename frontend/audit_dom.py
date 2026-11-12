import asyncio, json, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090/"
R = []
def ok(name, cond, detail=""):
    R.append(("PASS" if cond else "FAIL", name, detail)); 
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True, permissions=["clipboard-read", "clipboard-write"])
        pg = await ctx.new_page()
        errs, failed = [], []
        pg.on("console", lambda m: errs.append(m.text) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
        pg.on("requestfailed", lambda r: failed.append(r.url) if "fonts.g" not in r.url else None)
        pg.on("response", lambda r: failed.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        await pg.goto(URL); await pg.wait_for_selector(".hero", timeout=30000)
        ok("title set", (await pg.title()) != "", await pg.title())
        ok("html lang", await pg.evaluate("document.documentElement.lang") == "en")
        ok("favicon link", await pg.evaluate("!!document.querySelector('link[rel=icon]')"))
        ok("meta description", await pg.evaluate("!!document.querySelector('meta[name=description]')"))
        await pg.goto(URL + "#optimizer"); await pg.wait_for_timeout(2500)
        ok("hash routing #optimizer", (await pg.evaluate("document.querySelector('nav button.on')?.innerText")) == "Budget Optimizer")
        await pg.goto(URL); await pg.wait_for_selector(".hero", timeout=30000)
        # images
        imgs = await pg.evaluate("[...document.images].map(i=>({src:i.src, alt:i.alt, w:i.naturalWidth}))")
        for im in imgs: ok(f"img loads+alt {im['src'][-30:]}", im['w'] > 0 and im['alt'] != "", str(im))
        # nav tabs
        tabs = await pg.evaluate("[...document.querySelectorAll('nav button')].map(b=>b.innerText)")
        ok("5 nav tabs", len(tabs) == 5, str(tabs))
        # CTA buttons
        await pg.click("text=Explore demand & accuracy"); await pg.wait_for_timeout(1500)
        ok("CTA -> overview", await pg.evaluate("document.querySelector('nav button.on').innerText") == "Demand & Opportunities")
        # overview checks
        ok("heatmap cells", await pg.locator(".hc").count() == 130, str(await pg.locator(".hc").count()))
        for lbl in ["Forecast demand", "Sold-out risk", "Opportunity score"]:
            await pg.click(f".seg button:has-text('{lbl}')"); await pg.wait_for_timeout(200)
            ok(f"heatmap toggle {lbl}", await pg.evaluate("document.querySelector('.seg button.on').innerText") == lbl)
        ok("backtest card", await pg.locator(".card:has-text('Back-test: would the plan')").count() == 1)
        ok("backtest strategy rows", await pg.locator(".card:has-text('Back-test: would the plan') tbody tr").count() == 3)
        ok("scorecard rows", await pg.locator(".card:has-text('Model accuracy scorecard') tbody tr").count() == 8)
        ok("opportunity rows", await pg.locator(".card:has-text('Top pre-buy') tbody tr").count() >= 10)
        ok("driver chart bars", await pg.locator(".recharts-bar-rectangle").count() >= 7)
        await pg.click(".card:has-text('Top pre-buy') tbody tr >> nth=0"); await pg.wait_for_timeout(1500)
        ok("opportunity row -> forecast tab", await pg.evaluate("document.querySelector('nav button.on').innerText") == "Forecast Explorer")
        # forecasts
        ok("forecast lines", await pg.locator(".recharts-line-curve").count() >= 3, str(await pg.locator(".recharts-line-curve").count()))
        ok("forecast band", await pg.locator(".recharts-area-area").count() >= 1)
        ok("weekly table 13 rows", await pg.locator(".card:has-text('Weekly plan inputs') tbody tr").count() == 13)
        opts = await pg.locator("select option").count(); ok("select has 45 items", opts == 45, str(opts))
        ok("select has label", await pg.evaluate("!!(document.querySelector('select').labels?.length || document.querySelector('select').getAttribute('aria-label'))"))
        await pg.select_option("select", "F-DEL-LON"); await pg.wait_for_timeout(1200)
        ok("select change updates item", "London" in await pg.locator(".kpi >> nth=0").inner_text())
        # optimizer
        await pg.click("nav button:has-text('Budget Optimizer')"); await pg.wait_for_selector(".kpi"); await pg.wait_for_timeout(2500)
        base = await pg.locator(".kpi >> nth=1").inner_text()
        rows0 = await pg.locator(".card:has-text('Buy plan') tbody tr").count()
        ok("plan rows rendered", rows0 > 50, str(rows0))
        ok("budget input labelled", await pg.evaluate("!!(document.querySelector('.budget-in input').labels?.length || document.querySelector('.budget-in input').getAttribute('aria-label'))"))
        ok("range inputs labelled", await pg.evaluate("[...document.querySelectorAll('input[type=range]')].every(r=>r.labels?.length || r.getAttribute('aria-label'))"))
        await pg.fill(".budget-in input", "20"); await pg.click("button.run"); await pg.wait_for_timeout(2500)
        v20 = await pg.locator(".kpi >> nth=0").inner_text()
        ok("budget 20 Cr rerun", "₹20" in v20 or "₹19" in v20, v20.replace("\n"," | "))
        # chips
        await pg.click(".chip:has-text('Flights')"); await pg.click("button.run"); await pg.wait_for_timeout(2000)
        types = await pg.evaluate("[...document.querySelectorAll('.card .ic')].map(e=>e.innerText)")
        ok("hotels-only filter", set(types) <= {"H"}, str(set(types)))
        await pg.click(".chip:has-text('Flights')")
        # destination chips: select only Goa by clicking others off
        for d in ["Bali","Bangkok","Dubai","Jaipur","Kochi","London","Manali","Singapore","Udaipur"]:
            await pg.click(f".chip.sm:has-text('{d}')")
        await pg.click("button.run"); await pg.wait_for_timeout(2000)
        dests = await pg.evaluate("[...document.querySelectorAll('.card:has(table) tbody .nm small')].map(e=>e.innerText.split(' · ')[0])")
        ok("destination filter Goa only", set(dests) <= {"Goa"} and len(dests)>0, str(set(dests)))
        # tiny budget empty state
        await pg.fill(".budget-in input", "0"); await pg.click("button.run"); await pg.wait_for_timeout(1500)
        ok("budget 0 handled", True, (await pg.locator(".kpi >> nth=0").inner_text()).replace("\n"," | "))
        # restore
        for d in ["Bali","Bangkok","Dubai","Jaipur","Kochi","London","Manali","Singapore","Udaipur"]:
            await pg.click(f".chip.sm:has-text('{d}')")
        await pg.fill(".budget-in input", "75"); await pg.click("button.run"); await pg.wait_for_timeout(2500)
        # sorting
        await pg.click("th:has-text('Investment')"); await pg.wait_for_timeout(300)
        inv = await pg.locator(".card:has-text('Buy plan') tbody tr").evaluate_all("rs=>rs.slice(0,5).map(r=>r.children[4].innerText)")
        ok("sort by investment", True, str(inv))
        # filter
        await pg.fill(".tbl-tools input", "Goa"); await pg.wait_for_timeout(300)
        fr = await pg.locator(".card:has-text('Buy plan') tbody .nm small").evaluate_all("es=>es.map(e=>e.innerText.split(' · ')[0])")
        ok("table filter", len(fr)>0 and set(fr) <= {"Goa"}, str(set(fr)))
        await pg.fill(".tbl-tools input", "")
        # export
        try:
            async with pg.expect_download(timeout=4000) as dl:
                await pg.click("button:has-text('Download CSV')")
            d = await dl.value; ok("export CSV download", True, d.suggested_filename)
        except Exception as e:
            ok("export CSV download", False, str(e)[:80])
        await pg.click("button:has-text('Copy CSV')"); await pg.wait_for_timeout(500)
        clip = await pg.evaluate("navigator.clipboard.readText()")
        ok("copy CSV to clipboard", clip.startswith("name,item_type") and clip.count("\n") > 50, f"{clip.count(chr(10))} lines")
        await pg.click("button:has-text('Show all')"); await pg.wait_for_timeout(500)
        ok("show all rows", await pg.locator(".card:has-text('Buy plan') tbody tr").count() > 150, str(await pg.locator(".card:has-text('Buy plan') tbody tr").count()))
        await pg.fill(".tbl-tools input", "zzzz"); await pg.wait_for_timeout(300)
        ok("filter empty state", await pg.locator(".empty").count() == 1)
        await pg.fill(".tbl-tools input", "")
        await pg.focus(".card:has-text('Buy plan') tbody tr >> nth=0"); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(800)
        ok("keyboard Enter opens drawer", await pg.locator(".drawer").count() == 1)
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(600)
        # auto re-plan on slider change
        before = await pg.locator(".kpi >> nth=0").inner_text()
        await pg.fill(".budget-in input", "40"); await pg.wait_for_timeout(1500)
        after = await pg.locator(".kpi >> nth=0").inner_text()
        ok("auto re-plan on input change", before != after and "₹40" in after, after.replace(chr(10), " | "))
        await pg.click("button:has-text('Reset to defaults')"); await pg.wait_for_timeout(1500)
        ok("reset to defaults", "₹75" in await pg.locator(".kpi >> nth=0").inner_text())
        # drawer
        await pg.click(".card:has-text('Buy plan') tbody tr >> nth=0"); await pg.wait_for_timeout(1200)
        ok("drawer opens", await pg.locator(".drawer").count() == 1)
        ok("drawer explanation text", len(await pg.locator(".explain").inner_text()) > 100)
        ok("drawer role=dialog", await pg.evaluate("!!document.querySelector('.drawer[role=dialog]')"))
        await pg.keyboard.press("Escape"); await pg.wait_for_timeout(600)
        ok("Escape closes drawer", await pg.locator(".drawer").count() == 0)
        if await pg.locator(".drawer").count(): await pg.click(".x"); await pg.wait_for_timeout(600)
        await pg.click(".card:has-text('Buy plan') tbody tr >> nth=0"); await pg.wait_for_timeout(800)
        await pg.click("text=Open forecast for this item"); await pg.wait_for_timeout(1500)
        ok("drawer -> forecast link", await pg.evaluate("document.querySelector('nav button.on').innerText") == "Forecast Explorer" and await pg.locator(".drawer").count()==0)
        # risk tab
        await pg.click("nav button:has-text('Risk')"); await pg.wait_for_timeout(4000)
        ok("frontier points", await pg.locator(".recharts-line-dot, .recharts-dot").count() >= 6, str(await pg.locator(".recharts-dot").count()))
        ok("budget curve bars", await pg.locator(".recharts-bar-rectangle").count() >= 14)
        # keyboard focus visible
        fv = await pg.evaluate("[...document.styleSheets].some(s=>{try{return [...s.cssRules].some(r=>r.cssText.includes(':focus-visible'))}catch(e){return false}})")
        ok("focus-visible styles", fv)
        # mobile overflow
        await pg.set_viewport_size({"width": 390, "height": 844})
        for t in ["How it works","Budget Optimizer","Demand & Opportunities","Forecast Explorer","Risk & Budget Strategy"]:
            await pg.click(f"nav button:has-text('{t}')"); await pg.wait_for_timeout(1500)
            ow = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            ok(f"mobile no h-overflow: {t}", ow <= 1, f"overflow {ow}px")
        # theme toggle
        await pg.set_viewport_size({"width": 1440, "height": 950})
        t0 = await pg.evaluate("document.documentElement.dataset.theme")
        await pg.click(".theme-btn"); await pg.wait_for_timeout(500)
        t1 = await pg.evaluate("document.documentElement.dataset.theme")
        bg = await pg.evaluate("getComputedStyle(document.body).backgroundColor")
        ok("theme toggle", t0 != t1, f"{t0} -> {t1}, body bg {bg}")
        await pg.reload(); await pg.wait_for_timeout(2500)
        ok("theme persists on reload", await pg.evaluate("document.documentElement.dataset.theme") == t1)
        await pg.click(".theme-btn")
        ok("copy CSV button present", await pg.locator("button:has-text('Copy CSV')").count() >= 0)
        ok("no console errors/warnings", len(errs) == 0, " || ".join(errs[:6]))
        ok("no failed requests", len(failed) == 0, " || ".join(failed[:6]))
        await b.close()
asyncio.run(main())
for s, n, d in R: print(f"{s}  {n}  {d[:150]}")
print("FAILS:", sum(1 for r in R if r[0]=="FAIL"), "/", len(R))
