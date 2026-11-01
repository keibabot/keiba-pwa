"""Live HTTPS PWA smoke check. No race fixtures or artificial performance data."""
import asyncio
import json
import os
import re
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    out=Path("browser-artifacts")
    out.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={"width":1440,"height":1000})
        errors=[]
        page.on("pageerror",lambda error:errors.append(str(error)))
        expected=os.environ["EXPECTED_COMMIT"][:12]
        for attempt in range(20):
            response=await page.goto("https://keibabot.github.io/keiba-pwa/?verify="+expected,wait_until="networkidle")
            html=await page.content()
            match=re.search(r"画面版 ([0-9a-f]{12})",html)
            visible=match.group(1) if match else None
            acceptable=visible==expected
            if visible and not acceptable:
                try:
                    with urllib.request.urlopen("https://api.github.com/repos/keibabot/keiba-pwa/compare/"+os.environ["EXPECTED_COMMIT"]+"..."+visible) as response:
                        acceptable=json.load(response)["status"] in ("identical","ahead")
                except Exception:
                    acceptable=False
            if acceptable:
                audit=await page.evaluate("fetch('audit_report.json?t='+Date.now(),{cache:'no-store'}).then(r=>r.json())")
                if len(audit.get("strategy_conditions",[]))>0 and len(audit.get("legacy_unmatched_predictions",[]))==16:
                    break
            await asyncio.sleep(15)
        else:
            raise AssertionError("Expected Pages build not visible within 5 minutes")
        assert response.status==200
        await page.wait_for_function("document.querySelector('#modelRows').children.length===2")
        assert await page.locator("#commonRows tr").count()==7
        await page.wait_for_function("document.querySelector('#conditionROIRows').children.length>=10")
        assert audit["equal_budget_comparison"]["races"]==165
        assert audit["quality"]["legacy_snapshot_audit"]["different_snapshot_bet"]==2
        assert await page.locator("#venueCards .card").count()>=10
        assert not await page.evaluate("document.documentElement.scrollWidth>innerWidth")
        await page.screenshot(path=str(out/"desktop.png"))
        await page.locator("#historyScope").select_option("legacy")
        assert await page.locator("#historyRows details").count()==193
        await page.set_viewport_size({"width":390,"height":844})
        assert not await page.evaluate("document.documentElement.scrollWidth>innerWidth")
        await page.screenshot(path=str(out/"mobile.png"))
        await page.locator("#historyScope").select_option("live")
        summary={"url":page.url,"status":response.status,"console_errors":errors,"pipeline_status":await page.locator("#pipelineStatus").inner_text(),
            "live_predictions":await page.locator("#pickCards .pick").count(),"history_records":await page.locator("#historyRows details").count(),"condition_rows":await page.locator("#conditionROIRows tr").count()}
        assert not errors,errors
        # Check actual service-worker registration and offline JSON policy.
        await page.wait_for_function("navigator.serviceWorker.controller!==null",timeout=30000)
        await page.reload(wait_until="networkidle")
        await page.context.set_offline(True)
        await page.locator("#refresh").click()
        await page.wait_for_timeout(1500)
        assert await page.locator("#pickCards .pick").count()==0
        assert not await page.locator("#error").is_hidden()
        summary["offline_picks"]=0
        (out/"verification.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        print(json.dumps(summary,ensure_ascii=False))
        await browser.close()

asyncio.run(main())
