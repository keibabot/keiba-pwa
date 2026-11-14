"""UI-only inputs stay in an isolated browser, never in public prediction data."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    out=Path(os.environ.get('BROWSER_OUT','desk-artifacts'));out.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context(viewport={'width':390,'height':844},permissions=['clipboard-read','clipboard-write'])
        page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        url=os.environ.get('PWA_URL','http://127.0.0.1:8020/')
        response=await page.goto(url,wait_until='networkidle');assert response.status==200
        await page.wait_for_function('window.RaceDesk && window.XText')
        await page.locator('#dRoster').evaluate('(e)=>e.closest("details").open=true')
        await page.fill('#dTime','23:59');await page.fill('#dName','UI TEST ONLY')
        await page.fill('#dRoster','1 TEST A\n2 TEST B\n3 TEST C\n4 TEST D\n5 TEST E');await page.click('#dManual')
        await page.select_option('#dKind','trio');await page.select_option('#dMode','box');await page.fill('#dA','1,2,3,4,5')
        assert '10点 / 合計 1,000円' in await page.locator('#dTotals').inner_text()
        await page.select_option('#dKind','trifecta')
        assert '60点 / 合計 6,000円' in await page.locator('#dTotals').inner_text()
        assert await page.locator('#dCopy').is_disabled()
        assert not await page.locator('#dIncrease').is_hidden()
        await page.locator('#dCap').evaluate('(e)=>e.closest("details").open=true')
        await page.fill('#dCap','60');await page.fill('#dBudget','6000')
        await page.select_option('#dFormat','detail')
        assert '①→②→③' in await page.locator('#dPreview').input_value()
        assert '超過' in await page.locator('#dCount').inner_text()
        await page.locator('[data-odds]').first.fill('51.4');await page.locator('[data-odds]').first.press('Tab')
        first=await page.locator('.d-ticket').first.inner_text();assert '5,140円' in first and '-860円' in first and '手入力' in first
        await page.fill('#dScratch','5');assert '24点 / 合計 2,400円' in await page.locator('#dTotals').inner_text()
        await page.fill('#dScratch','');assert '60点 / 合計 6,000円' in await page.locator('#dTotals').inner_text()
        text=await page.locator('#dPreview').input_value();await page.fill('#dPreview',text.replace('合計6000円','合計100円'))
        assert await page.locator('#dCopy').is_disabled();await page.click('#dRegenerate')
        await page.click('#dCopy');await page.wait_for_function("document.querySelector('#dCopyStatus').textContent.includes('コピーしました')")
        assert await page.evaluate('navigator.clipboard.readText()')==await page.locator('#dPreview').input_value()
        saved=await page.evaluate("JSON.parse(localStorage.getItem('trifecta-desk-v1'))")
        k=next(iter(saved['versions']));v=saved['versions'][k][0]
        assert v['copied_at'] and not v['posted_at'] and len(v['cart']['rows'])==60
        await page.evaluate("RaceDesk.receive(null,null)")
        assert '60点' in await page.locator('#dTotals').inner_text()
        await page.reload(wait_until='networkidle');await page.select_option('#dScope','history');await page.select_option('#dRace',k)
        assert '60点 / 合計 6,000円' in await page.locator('#dTotals').inner_text()
        assert await page.locator('[data-odds]').first.input_value()=='51.4'
        assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        await page.screenshot(path=str(out/'mobile.png'))
        await page.set_viewport_size({'width':1440,'height':1000});assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        await page.screenshot(path=str(out/'desktop.png'))
        await context.set_offline(True);await page.click('#dRefresh');await page.wait_for_timeout(500)
        assert '60点' in await page.locator('#dTotals').inner_text();assert '古い' in await page.locator('.d-ticket').first.inner_text()
        assert not errors,errors
        proof={'url':url,'http_status':response.status,'page_errors':errors,'mobile_overflow':False,'trio_box_points':10,'trifecta_box_points':60,'default_1200_limit_blocks_copy':True,'copy_matches_preview':True,'copied_not_posted':True,'reload_preserves_edit_and_odds':True,'offline_editing':True,'fixtures_only':True}
        (out/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(proof,ensure_ascii=False))
        await browser.close()
asyncio.run(main())
