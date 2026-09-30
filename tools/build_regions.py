# -*- coding: utf-8 -*-
"""
實價登錄「查房價」資料產生器（中彰投，按行政區拆檔）
======================================================
從內政部開放資料下載台中市、彰化縣、南投縣近兩年的買賣資料，
每個行政區存成一個小檔，網頁選到哪一區才下載那一區，網站才不會變慢。

產出：
  data/index.js     縣市與行政區目錄
  data/B-01.js ...  各行政區的成交明細
由 tools/update.py 呼叫
"""
import csv, io, json, os, re, datetime, urllib.request
from build_home import BAD, cn_num, roc_to_date, FW
import lvr

COUNTIES = [('B', '台中市', ['臺中市', '台中市']),
            ('N', '彰化縣', ['彰化縣']),
            ('M', '南投縣', ['南投縣'])]
QUARTERS = 8          # 抓幾季（兩年，給走勢圖用）
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
M2_TO_PING = 0.3025

# 型態代碼（網頁用同一份順序）
TYPES = ['透天', '華廈', '大樓', '公寓', '套房', '店面', '辦公', '廠房', '其他', '土地']


def type_of(x):
    if x['交易標的'] == '土地':
        return 9
    b = x['建物型態']
    for key, code in (('透天', 0), ('華廈', 1), ('住宅大樓', 2), ('公寓', 3), ('套房', 4),
                      ('店面', 5), ('辦公', 6), ('工廠', 7), ('廠辦', 7), ('倉庫', 7)):
        if b.startswith(key):
            return code
    return 8


def road_of(addr, names, district):
    """門牌只留到路／街／巷弄（完整門牌可以問安娜）。"""
    a = addr.translate(FW)
    for n in names + [district]:
        a = a.replace(n, '')
    a = re.sub('[-]', '', a)   # 地政造字，瀏覽器顯示不出來
    m = (re.match(r'(.+?(?:路|街|大道)(?:[一二三四五六七八九十]+段)?(?:\d+巷)?(?:\d+弄)?)', a)
         or re.match(r'(\D+?巷(?:\d+弄)?)', a))
    if m:
        return m.group(1)
    m = re.match(r'(\D+?段)', a)            # 土地只有地段，例如「成功段」
    return m.group(1) if m else ''


def num(v):
    try:
        return float(v or 0)
    except ValueError:
        return 0.0


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    index = {'updated': datetime.date.today().isoformat(), 'types': TYPES, 'counties': []}
    latest = None
    for code, cname, names in COUNTIES:
        rows = lvr.load_county(code, QUARTERS)

        seen, by_dist = set(), {}
        for x in rows:
            if x['編號'] in seen:
                continue
            seen.add(x['編號'])
            if x['交易標的'] == '車位' or any(b in x['備註'] for b in BAD) or not x['單價元平方公尺']:
                continue
            d = roc_to_date(x['交易年月日'])
            if not d:
                continue
            latest = max(latest or d, d)
            t = type_of(x)
            built = roc_to_date(x['建築完成年月'])
            age = round((d - built).days / 365.25) if built and t != 9 else None
            bld = num(x['建物移轉總面積平方公尺']) - num(x['車位移轉總面積平方公尺'])
            fl, tot = x['移轉層次'], cn_num(x['總樓層數'])
            if t == 9:
                floor = ''
            elif fl.startswith('全') or t == 0:
                floor = f'共{tot}' if tot else ''
            else:
                f1 = cn_num(fl.split('，')[0].replace('層', ''))
                floor = f'{f1 or ""}/{tot}' if tot else ''
            by_dist.setdefault(x['鄉鎮市區'], []).append([
                d.strftime('%Y%m%d'),                                   # 0 成交日
                t,                                                      # 1 型態代碼
                road_of(x['土地位置建物門牌'], names, x['鄉鎮市區']),     # 2 路段
                round(int(x['總價元'] or 0) / 10000),                    # 3 總價（萬）
                round(float(x['單價元平方公尺']) * 3.305785 / 10000, 1),  # 4 單價（萬/坪）
                round(bld * M2_TO_PING, 1) if t != 9 else 0,            # 5 建坪
                round(num(x['土地移轉總面積平方公尺']) * M2_TO_PING, 1),  # 6 地坪
                floor,                                                  # 7 樓別
                age,                                                    # 8 屋齡
                x['建物現況格局-房'] or '',                              # 9 房數
                1 if x['車位類別'] else 0,                               # 10 含車位
            ])

        dists = []
        for i, (name, lst) in enumerate(sorted(by_dist.items(), key=lambda kv: -len(kv[1]))):
            fid = f'{code}-{i + 1:02d}'
            lst.sort(key=lambda r: r[0], reverse=True)
            with open(os.path.join(OUT_DIR, fid + '.js'), 'w', encoding='utf-8') as f:
                f.write('/* 自動產生，請勿手動修改 */\nwindow.RP_LOAD&&RP_LOAD(' + json.dumps(fid) + ',' +
                        json.dumps(lst, ensure_ascii=False, separators=(',', ':')) + ');\n')
            dists.append({'f': fid, 'name': name, 'n': len(lst)})
        index['counties'].append({'code': code, 'name': cname, 'districts': dists})
        print(f'{cname}：{len(dists)} 個行政區，{sum(d["n"] for d in dists)} 筆')

    index['latest'] = latest.strftime('%Y-%m') if latest else ''
    with open(os.path.join(OUT_DIR, 'index.js'), 'w', encoding='utf-8') as f:
        f.write('/* 自動產生，請勿手動修改 */\nwindow.RP_INDEX=' + json.dumps(index, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print('完成 →', os.path.abspath(OUT_DIR))


if __name__ == '__main__':
    main()
