import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
SL = Path('/home/claude/deckroot/project/slides')
CSS = """*{margin:0;box-sizing:border-box} html,body{width:1920px;height:1080px;overflow:hidden}
section{position:relative;width:1920px;height:1080px;overflow:hidden} aside{display:none}
ul,ol{padding-left:1.2em} table{border-spacing:0} a{color:inherit}
x-shape[kind=arrow-right]{display:block;clip-path:polygon(0 30%,60% 30%,60% 0,100% 50%,60% 100%,60% 70%,0 70%)}"""
END = """<section style="background:#FAFAF9;color:#18181B;font-family:'Plus Jakarta Sans',Arial,sans-serif;padding:140px;display:flex;flex-direction:column;justify-content:center;gap:56px">
<p style="font-size:24px;letter-spacing:3px;color:#71717A;font-weight:700">TEAM VOID · HACKATHON · INVENTORY OPTIMIZATION FOR TBO.COM</p>
<h1 style="font-family:Fraunces,Georgia,serif;font-size:110px;font-weight:600;line-height:1.05;letter-spacing:-2px">TBO Inventory Intelligence</h1>
<div style="display:grid;grid-template-columns:260px 1fr;row-gap:22px;font-size:36px">
<span style="color:#71717A">Live demo</span><b>tbo-inventory-optimizer-sggo.vercel.app</b>
<span style="color:#71717A">Code</span><b>github.com/srujanmh/tbo-inventory-optimizer</b>
<span style="color:#71717A">Report</span><b>linked in the repository README</b></div>
<p style="font-size:26px;color:#71717A">All figures come from a synthetic dataset: simulated results, not actual TBO profit.</p></section>"""
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1920,"height":1080})
        for sid in ['cover','problem','pipeline','impact','end']:
            body = END if sid == 'end' else (SL/f'{sid}.html').read_text()
            await pg.set_content(f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>{body}</body></html>"); await pg.wait_for_timeout(700)
            await pg.screenshot(path=f'stills/{sid}.jpg', type='jpeg', quality=92)
        await b.close()
asyncio.run(main())
