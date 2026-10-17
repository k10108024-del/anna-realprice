# -*- coding: utf-8 -*-
"""
內政部實價登錄資料讀取（兩支產生程式共用）
======================================================
資料有兩種來源，合併後用「編號」去重：
  1. 整季資料（DownloadSeason）：一季公布一次，最完整
  2. 本期資料（每月 1、11、21 日發布的最新一批）：
     每次執行都把最新一批存進 raw/current/，累積起來，
     這樣還沒公布整季資料的最近幾個月也看得到
另外還有三份附表（土地、建物、車位明細），用「編號」對回主檔
"""
import csv, io, os, re, zipfile, datetime, urllib.request

ROOT = os.path.join(os.path.dirname(__file__), '..')
RAW_CURRENT = os.path.join(ROOT, 'raw', 'current')
UA = {'User-Agent': 'Mozilla/5.0'}


def _get(url, timeout=120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def _parse(raw_text, first='鄉鎮市區'):
    """主檔第一欄是「鄉鎮市區」，附表是「編號」；不是預期的開頭（例如還沒公布的季別）回傳 None"""
    if not raw_text.startswith(first):
        return None
    r = list(csv.reader(io.StringIO(raw_text)))
    return [dict(zip(r[0], x)) for x in r[2:]]   # 第二列是英文欄名，跳過


def seasons_back(n):
    """從本季往回列出 n+1 個季別代碼（例如 115S2），第一個可能還沒公布。"""
    t = datetime.date.today()
    y, q = t.year - 1911, (t.month - 1) // 3 + 1
    out = []
    for _ in range(n + 1):
        out.append(f'{y}S{q}')
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


ATTACH = ('land', 'build', 'park')   # 附表：土地明細、建物明細、車位明細


def fetch_season(county, season, kind=''):
    """kind 空白＝主檔；'land'／'build'／'park'＝附表"""
    suffix = f'_{kind}' if kind else ''
    raw = _get(f'https://plvr.land.moi.gov.tw/DownloadSeason?season={season}&fileName={county}_lvr_land_a{suffix}.csv')
    return _parse(raw.decode('utf-8-sig', 'ignore'), '編號' if kind else '鄉鎮市區')


def save_current_batch(counties):
    """下載本期（最新一批）資料，存到 raw/current/<期間>/<縣市>.csv。已經存過就略過。"""
    data = _get('https://plvr.land.moi.gov.tw/Download?type=zip&fileName=lvr_landcsv.zip', timeout=300)
    z = zipfile.ZipFile(io.BytesIO(data))
    info = z.read('build_time.xml').decode('utf-8', 'ignore')
    d = re.findall(r'(\d+)年(\d+)月(\d+)日', info)
    tag = '-'.join(f'{int(y):03d}{int(m):02d}{int(dd):02d}' for y, m, dd in d[:2]) or datetime.date.today().isoformat()
    folder = os.path.join(RAW_CURRENT, tag)
    if os.path.isdir(folder) and all(os.path.exists(os.path.join(folder, f'{c}_{k}.csv')) for c in counties for k in ATTACH):
        print(f'本期 {tag} 已經存過')
        return tag
    os.makedirs(folder, exist_ok=True)   # 已經存過主檔、但還沒有附表（2026-10 以前存的）就補存附表
    for c in counties:
        for kind in ('',) + ATTACH:
            suffix = f'_{kind}' if kind else ''
            name = f'{c.lower()}_lvr_land_a{suffix}.csv'
            if name in z.namelist():
                with open(os.path.join(folder, f'{c}{suffix}.csv'), 'wb') as f:
                    f.write(z.read(name))
    print(f'本期 {tag} 已存檔')
    return tag


def load_current(county, kind=''):
    rows = []
    if not os.path.isdir(RAW_CURRENT):
        return rows
    suffix = f'_{kind}' if kind else ''
    for tag in sorted(os.listdir(RAW_CURRENT)):
        p = os.path.join(RAW_CURRENT, tag, f'{county}{suffix}.csv')
        if os.path.exists(p):
            rows += _parse(open(p, encoding='utf-8-sig', errors='ignore').read(), '編號' if kind else '鄉鎮市區') or []
    return rows


def load_county(county, quarters, attach=None):
    """整季資料（最近 quarters 季）＋累積的本期資料，依編號去重。
    attach 給一個 dict 時，順便下載同樣季別的附表，放進 attach[kind][編號] = [列, 列…]"""
    rows, got = [], 0
    for s in seasons_back(quarters + 1):
        d = fetch_season(county, s)
        if d is None:
            print(f'{county} {s} 尚未公布，略過')
            continue
        rows += d
        got += 1
        print(f'{county} {s} 下載 {len(d)} 筆')
        if attach is not None:
            for kind in ATTACH:
                _add_attach(attach, kind, fetch_season(county, s, kind) or [])
        if got >= quarters:
            break
    if attach is not None:
        for kind in ATTACH:
            _add_attach(attach, kind, load_current(county, kind))
    cur = load_current(county)
    print(f'{county} 本期累積 {len(cur)} 筆')
    seen, out = set(), []
    for x in rows + cur:
        k = x.get('編號')
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def _add_attach(attach, kind, rows):
    """附表同一個編號可能出現在整季和本期兩邊：以先讀到的那份為準，不重複加"""
    got = attach.setdefault(kind, {})
    fresh = {}
    for x in rows:
        k = x.get('編號')
        if k and k not in got:
            fresh.setdefault(k, []).append(x)
    got.update(fresh)


def prune_current(keep_days=800):
    """太舊的本期資料（整季資料早就涵蓋了）刪掉，避免越存越多。"""
    if not os.path.isdir(RAW_CURRENT):
        return
    limit = (datetime.date.today() - datetime.timedelta(days=keep_days))
    limit_tag = f'{limit.year - 1911:03d}{limit.month:02d}{limit.day:02d}'
    for tag in os.listdir(RAW_CURRENT):
        if tag[:7] < limit_tag:
            p = os.path.join(RAW_CURRENT, tag)
            for f in os.listdir(p):
                os.remove(os.path.join(p, f))
            os.rmdir(p)
            print('刪除舊的本期資料', tag)
