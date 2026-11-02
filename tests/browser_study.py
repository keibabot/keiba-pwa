"""Check real research output on desktop/mobile, including offline behavior.

PWA_URL=http://127.0.0.1:8011/ python tests/browser_study.py
Default: actual public HTTPS URL. Does not invent predictions/results.
"""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    url = os.environ.get('PWA_URL', 'https://keibabot.github.io/keiba-pwa/')
    out = Path(os.environ.get('BROWSER_OUT', 'browser-study-artifacts')); out.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
        response = await page.goto(url, wait_until='networkidle')
        assert response.status == 200
        await page.wait_for_function("document.querySelectorAll('#basketStudyRows tr').length===7")
        for scope, n in [('9', 7), ('10', 7), ('rolling', 7), ('common', 12)]:
            await page.select_option('#studyScope', scope)
            assert await page.locator('#basketStudyRows tr').count() == n
        for dimension in ('track', 'distance_band', 'going', 'runners_band', 'surface'):
            await page.select_option('#sliceDimension', dimension)
            assert await page.locator('#sliceRows tr').count() > 0
        assert await page.locator('#referenceCards article').count() == 3
        assert await page.locator('#foldRows tr').count() == 4
        assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        await page.screenshot(path=str(out/'desktop.png'))
        await page.set_viewport_size({'width': 390, 'height': 844})
        assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        await page.select_option('#studyScope', '10')
        await page.locator('#basketStudy').scroll_into_view_if_needed()
        await page.screenshot(path=str(out/'mobile.png'))
        data = await page.evaluate("fetch('strategy_report.json?t='+Date.now(),{cache:'no-store'}).then(r=>r.json())")
        summary = {'url': url, 'http_status': response.status, 'page_errors': errors,
            'rules_sha256': data['rules_sha256'], 'research_version': data['version'],
            'reference_people': 3, 'rolling_folds': 4, 'mobile_overflow': False,
            'live_research_rows': await page.locator('#basketLiveRows tr').count(),
            'build': await page.locator('.status').inner_text()}
        await page.wait_for_function('navigator.serviceWorker.controller!==null')
        await page.reload(wait_until='networkidle')
        await page.context.set_offline(True)
        await page.click('#refresh')
        await page.wait_for_timeout(500)
        assert await page.locator('#pickCards .pick').count() == 0
        assert not await page.locator('#error').is_hidden()
        summary['offline_picks'] = 0
        assert not errors, errors
        (out/'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False))
        await browser.close()

asyncio.run(main())
