# -*- coding: utf-8 -*-
"""
Bing 網站管理員工具數據同步（GitHub 機器人每天執行，也可以手動執行）
  Bing 會擋 Cloudflare 的網路，皮皮後台（crm-api）沒辦法自己去抓，所以由這裡抓好再送過去：
  1. 用 Bing API 抓 annahouse.tw 的搜尋關鍵字、每頁點擊、每天曝光、收錄頁數（原始資料，不整理）
  2. POST 到 crm-api 的 /bing/ingest，皮皮「官網數據」再依查詢期間整理
需要的 GitHub secret：BING_API_KEY（Bing 網站管理員工具 → 設定 → API 存取）、BING_INGEST_TOKEN（跟 crm-api 的 secret 相同）
資料只送到皮皮後台，不存進這個公開的專案；log 也不印金鑰
用法：python tools/bing_sync.py
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

SITE = 'https://annahouse.tw/'
CRM = 'https://crm-api.k10108024.workers.dev/bing/ingest'
PARTS = [('queries', 'GetQueryStats'), ('pages', 'GetPageStats'), ('traffic', 'GetRankAndTrafficStats'), ('crawl', 'GetCrawlStats')]


def bing(method, key):
    url = ('https://ssl.bing.com/webmaster/api.svc/json/' + method + '?' +
           urllib.parse.urlencode({'siteUrl': SITE, 'apikey': key}))
    for i in range(3):   # 偶爾限流：等一下再試
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode('utf-8')).get('d') or []
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'replace')[:200]
            if 'Throttle' in msg and i < 2:
                time.sleep(20)
                continue
            raise RuntimeError(f'HTTP {e.code} {msg}')


def main():
    key, token = os.environ.get('BING_API_KEY'), os.environ.get('BING_INGEST_TOKEN')
    if not key or not token:
        sys.exit('缺少 BING_API_KEY 或 BING_INGEST_TOKEN')
    out, errors = {}, {}
    for name, method in PARTS:
        try:
            out[name] = bing(method, key)
            print(f'{name}：{len(out[name])} 筆')
        except Exception as e:
            out[name] = None
            errors[name] = str(e).replace(key, '***')[:200]
            print(f'{name}：失敗 {errors[name]}')
        time.sleep(2)
    out['errors'] = errors
    req = urllib.request.Request(CRM, data=json.dumps(out, ensure_ascii=False).encode('utf-8'), method='POST',
                                 headers={'content-type': 'application/json', 'x-ingest-token': token})
    with urllib.request.urlopen(req, timeout=60) as r:
        print('送進皮皮後台：', r.status, r.read().decode('utf-8')[:200])
    if len(errors) == len(PARTS):
        sys.exit('Bing 四項都抓不到')


if __name__ == '__main__':
    main()
