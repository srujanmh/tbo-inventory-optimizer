import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
SL = Path('/home/claude/deckroot/project/slides')
CSS = """*{margin:0;box-sizing:border-box} html,body{width:1920px;height:1080px;overflow:hidden}
section{position:relative;width:1920px;height:1080px;overflow:hidden} aside{display:none}
ul,ol{padding-left:1.2em} table{border-spacing:0} a{color:inherit}
x-shape[kind=arrow-right]{display:block;clip-path:polygon(0 30%,60% 30%,60% 0,100% 50%,60% 100%,60% 70%,0 70%)}"""
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1920,"height":1080})
        for sid in ['cover','problem','pipeline','impact']:
            html = f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>{(SL/f'{sid}.html').read_text()}</body></html>"
            await pg.set_content(html); await pg.wait_for_timeout(600)
            await pg.evaluate('''() => { for (const p of document.querySelectorAll('p')) {
                if (p.textContent.includes('[Team name]')) p.textContent = 'TEAM VOID · Prototype submission';
                if (p.textContent.includes('[GitHub link]')) p.textContent = 'Live demo: claude.ai/artifact/XM6d4qBCJyEeFcAQNUKR3n · Built on a realistic synthetic dataset; swap in real data and retrain'; } }''')
            await pg.screenshot(path=f'stills/{sid}.jpg', type='jpeg', quality=92)
        await b.close()
asyncio.run(main())
