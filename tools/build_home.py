# -*- coding: utf-8 -*-
"""
首頁「實價行情速報」資料產生器（草屯鎮、南投市）
======================================================
從內政部「不動產成交案件實際資訊」開放資料下載南投縣買賣資料，
整理成 realprice/data.js，給 realprice/index.html 使用。

由 tools/update.py 呼叫，產出 data/data.js

要改統計的鄉鎮，改下面的 TOWNS。
"""
import csv, io, json, os, re, statistics, urllib.request, datetime

COUNTY = 'M'                      # 內政部縣市代碼：M = 南投縣
TOWNS = ['草屯鎮', '南投市']        # 要統計的鄉鎮
TREND_QUARTERS = 8                # 走勢圖要畫幾季
OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'data.js')

# 備註裡出現這些字的，是價格不正常的特殊交易，不列入統計
BAD = ['親友', '員工', '共有人', '政府機關', '協議價購', '地清', '公共設施保留地', '畸零地',
       '分件', '瑕疵', '急買', '急賣', '債權', '債務', '拍賣', '含租約', '特殊', '凶宅', '受債權']

M2_TO_PING = 0.3025
BLD_TYPES = [('透天厝', '透天厝'), ('華廈', '華廈'), ('住宅大樓', '住宅大樓'), ('公寓', '公寓')]
LAND_TYPES = [  # (顯示名稱, 判斷函式)
    ('都市・住宅區', lambda x: x['都市土地使用分區'] == '住'),
    ('都市・商業區', lambda x: x['都市土地使用分區'] == '商'),
    ('都市・農業區', lambda x: x['都市土地使用分區'] == '農'),
    ('非都市・乙種建地', lambda x: x['非都市土地使用編定'] == '乙種建築用地'),
    ('非都市・農牧用地', lambda x: x['非都市土地使用編定'] == '農牧用地'),
]
MIN_N = 8   # 筆數少於這個就不顯示，避免一兩筆就代表行情


FW = str.maketrans('０１２３４５６７８９－', '0123456789-')
CN = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def cn_num(s):
    s = s.replace('層', '')
    if not s or any(c not in CN for c in s):
        return None
    if s == '十':
        return 10
    if '十' in s:
        a, b = s.split('十')
        return (CN[a] if a else 1) * 10 + (CN[b] if b else 0)
    return CN[s]


def road_of(addr, town):
    """門牌只留到路／街／巷弄，完整門牌請洽安娜。"""
    a = addr.translate(FW).replace('南投縣', '').replace(town, '')
    a = re.sub('[-]', '', a)   # 地政造字（私人區字元）瀏覽器顯示不出來，拿掉
    m = (re.match(r'(.+?(?:路|街|大道)(?:[一二三四五六七八九十]+段)?(?:\d+巷)?(?:\d+弄)?)', a)
         or re.match(r'(\D+?巷(?:\d+弄)?)', a))   # 鄉間的「○○巷」沒有路名
    return m.group(1) if m else ''


def quantile(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def summary(vals):
    return {'n': len(vals), 'med': round(statistics.median(vals), 2),
            'p25': round(quantile(vals, .25), 2), 'p75': round(quantile(vals, .75), 2)}


def roc_to_date(s):
    s = s.strip()
    if len(s) != 7:
        return None
    try:
        return datetime.date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except ValueError:
        return None


def main():
    import lvr
    rows = lvr.load_county(COUNTY, TREND_QUARTERS)
    seasons = [x for x in lvr.seasons_back(TREND_QUARTERS + 1)][-TREND_QUARTERS:]

    seen, clean = set(), []
    for x in rows:
        if x['編號'] in seen or x['鄉鎮市區'] not in TOWNS:
            continue
        seen.add(x['編號'])
        if any(b in x['備註'] for b in BAD) or not x['單價元平方公尺']:
            continue
        d = roc_to_date(x['交易年月日'])
        if not d:
            continue
        x['_d'] = d
        x['_unit'] = float(x['單價元平方公尺']) * 3.305785 / 10000   # 萬/坪
        clean.append(x)

    # 近一年：以資料中最新交易月份往回 12 個月
    last = max(x['_d'] for x in clean)
    end = datetime.date(last.year, last.month, 1)
    m = end.year * 12 + end.month - 1 - 11   # 往回 11 個月，連同最新月份共 12 個月
    start = datetime.date(m // 12, m % 12 + 1, 1)
    year = [x for x in clean if x['_d'] >= start]

    is_bld = lambda x: x['交易標的'].startswith('房地')
    out = {'updated': datetime.date.today().isoformat(),
           'period': [start.strftime('%Y-%m'), end.strftime('%Y-%m')],
           'towns': {}, 'trend': {}, 'deals': []}

    for t in TOWNS:
        ty_rows = [x for x in year if x['鄉鎮市區'] == t]
        bld = []
        for name, key in BLD_TYPES:
            v = [x['_unit'] for x in ty_rows if is_bld(x) and x['建物型態'].startswith(key)]
            if len(v) >= MIN_N:
                bld.append({'type': name, **summary(v)})
        land = []
        for name, fn in LAND_TYPES:
            v = [x['_unit'] for x in ty_rows if x['交易標的'] == '土地' and fn(x)]
            if len(v) >= MIN_N:
                land.append({'type': name, **summary(v)})
        out['towns'][t] = {'bld': bld, 'land': land}

        # 每季走勢：透天厝、電梯（華廈＋住宅大樓）
        tr = {}
        for x in clean:
            if x['鄉鎮市區'] != t or not is_bld(x):
                continue
            q = f"{x['_d'].year}Q{(x['_d'].month - 1) // 3 + 1}"
            k = '透天厝' if x['建物型態'].startswith('透天厝') else (
                '電梯大樓' if x['建物型態'][:2] in ('華廈', '住宅') else None)
            if k:
                tr.setdefault(k, {}).setdefault(q, []).append(x['_unit'])
        # 太早的季別只有少數補登的案件，不算
        first_q = min(f"{int(x[:3]) + 1911}Q{x[-1]}" for x in seasons)
        # 最新一季常因申報延遲只有少數幾筆，筆數不足的季別不畫，免得走勢被拉歪
        out['trend'][t] = {k: [[q, round(statistics.median(v), 2), len(v)]
                               for q, v in sorted(qs.items()) if len(v) >= 15 and q >= first_q][-TREND_QUARTERS:]
                           for k, qs in tr.items()}

    # 成交明細（近一年、房屋類）
    for x in sorted(year, key=lambda x: x['_d'], reverse=True):
        if not is_bld(x):
            continue
        ty = next((n for n, k in BLD_TYPES if x['建物型態'].startswith(k)), None)
        if not ty:
            continue
        built = roc_to_date(x['建築完成年月'])
        age = round((x['_d'] - built).days / 365.25) if built else None
        area = float(x['建物移轉總面積平方公尺'] or 0) - float(x['車位移轉總面積平方公尺'] or 0)
        fl, tot = x['移轉層次'], cn_num(x['總樓層數'])
        floor = f'共{tot}樓' if (fl.startswith('全') or ty == '透天厝') and tot else (
            f'{cn_num(fl.split("，")[0]) or fl}/{tot}樓' if tot else '')
        out['deals'].append([
            x['_d'].strftime('%Y-%m-%d'), x['鄉鎮市區'], ty, road_of(x['土地位置建物門牌'], x['鄉鎮市區']),
            round(int(x['總價元']) / 10000), round(area * M2_TO_PING, 1), round(x['_unit'], 2),
            age, floor, x['建物現況格局-房'] or '', 1 if x['車位類別'] else 0,
        ])

    js = ('/* 自動產生，請勿手動修改。重新產生：python tools/build_realprice.py */\n'
          'window.RP=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(js)
    print(f'完成：期間 {out["period"]}，明細 {len(out["deals"])} 筆 → {os.path.abspath(OUT)}')


if __name__ == '__main__':
    main()
