# -*- coding: utf-8 -*-
"""
實價登錄「歷次」：同一個門牌（同一層）從 2012 年起的所有成交
======================================================
內政部實價登錄 2.0 已經把 2012 年以來的門牌完整公開，所以可以用「門牌＋移轉層次」比對同一戶。

資料怎麼累積（避免每次都重抓十幾年的資料，也避免 GitHub 專案越存越大）：
  raw/hist/B-2013.json.gz …  每個縣市、每個成交年份一份，{編號: 精簡列}；只存「兩年前以前」的年份（之後幾乎不會再變），
                              第一次用 backfill 從 101S1 抓到現在。最近兩年每次執行本來就會重新下載（build_regions 讀的那批），
                              不存檔，直接合併使用；跨年時，掉出最近兩年的那一年就會存成年份檔
產出：
  data/h/<行政區檔名>-<分片>.js   只放「成交兩次以上」的門牌，依門牌雜湊分片，網頁點開明細才讀那一片
用法：
  第一次（本機跑一次就好，約 10～20 分鐘）：python tools/build_history.py backfill
  平常由 build_regions.main() 呼叫 merge() 和 export()
"""
import gzip, json, os, re, sys, zlib

sys.path.insert(0, os.path.dirname(__file__))
import lvr
from build_home import BAD, cn_num, roc_to_date, FW

ROOT = os.path.join(os.path.dirname(__file__), '..')
HIST_DIR = os.path.join(ROOT, 'raw', 'hist')
OUT_DIR = os.path.join(ROOT, 'data', 'h')
FIRST_SEASON = (101, 1)   # 內政部開放資料從民國 101 年第 1 季開始（實價登錄 2012 年 8 月上路）
SHARDS = 8                # 每個行政區分幾片（一片太大手機下載會慢）
M2_TO_PING = 0.3025
CN_FLOOR = re.compile(r'([一二三四五六七八九十]+)樓')


def clean_addr(addr, names, district):
    """顯示用門牌：去掉縣市、行政區、里鄰，全形數字改半形，地政造字拿掉"""
    a = (addr or '').translate(FW).replace('巿', '市')
    for n in names + [district]:
        a = a.replace(n, '')
    a = re.sub(r'[^\s路街道巷段]{1,4}里\d+鄰', '', a)   # 例如「枇杷里28鄰」
    a = re.sub(r'\d+鄰', '', a)
    a = re.sub('[-]', '', a)               # 地政造字（私用區），瀏覽器顯示不出來
    return a.strip()


def addr_key(x, names):
    """比對同一戶用的鍵：門牌（樓層改阿拉伯數字）＋移轉層次"""
    a = clean_addr(x['土地位置建物門牌'], names, x['鄉鎮市區'])
    a = CN_FLOOR.sub(lambda m: f'{cn_num(m.group(1)) or m.group(1)}樓', a)
    a = re.sub(r'\s+', '', a)
    return a + '|' + re.sub(r'\s+', '', x.get('移轉層次') or '')


def slim(x, names):
    """一筆成交 → 精簡列：[鍵, 行政區, 成交日, 型態, 總價萬, 單價萬/坪, 建坪, 地坪, 移轉層次, 特殊交易]"""
    from build_regions import type_of
    d = roc_to_date(x['交易年月日'])
    if not d or x['交易標的'] == '車位':
        return None
    try:
        unit = round(float(x['單價元平方公尺'] or 0) * 3.305785 / 10000, 1)
    except ValueError:
        unit = 0
    num = lambda v: float(v or 0) if re.match(r'^[\d.]+$', v or '') else 0.0
    park = x.get('車位移轉總面積平方公尺', x.get('車位移轉總面積(平方公尺)'))   # 舊年份欄名有括號
    bld = num(x.get('建物移轉總面積平方公尺')) - num(park)
    t = type_of(x)
    return [addr_key(x, names), x['鄉鎮市區'], d.strftime('%Y%m%d'), t,
            round(num(x.get('總價元')) / 10000), unit,
            round(bld * M2_TO_PING, 1) if t != 9 else 0, round(num(x.get('土地移轉總面積平方公尺')) * M2_TO_PING, 1),
            x.get('移轉層次') or '', 1 if any(b in (x.get('備註') or '') for b in BAD) else 0]


def _frozen_until():
    """存成年份檔的最後一年：今年往前兩年（例如 2026 年時存到 2024 年）"""
    import datetime
    return datetime.date.today().year - 2


def load(code):
    """讀這個縣市所有年份檔，合成 {編號: 精簡列}"""
    hist = {}
    if not os.path.isdir(HIST_DIR):
        return hist
    for f in sorted(os.listdir(HIST_DIR)):
        if f.startswith(code + '-') and f.endswith('.json.gz'):
            with gzip.open(os.path.join(HIST_DIR, f), 'rt', encoding='utf-8') as fh:
                hist.update(json.load(fh))
    return hist


def save(code, hist):
    """依成交年份存檔，只存到 _frozen_until() 那一年；內容沒變的年份檔不重寫（檔頭時間固定為 0，內容一樣檔案就一樣）"""
    os.makedirs(HIST_DIR, exist_ok=True)
    by_year = {}
    for k, r in hist.items():
        by_year.setdefault(int(r[2][:4]), {})[k] = r
    for y, part in by_year.items():
        if y > _frozen_until():
            continue
        data = json.dumps(part, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
        p = os.path.join(HIST_DIR, f'{code}-{y}.json.gz')
        new = gzip.compress(data, compresslevel=9, mtime=0)
        if os.path.exists(p) and open(p, 'rb').read() == new:
            continue
        open(p, 'wb').write(new)


def merge(code, names, rows):
    """年份檔＋這次讀到的成交（最近兩年＋本期）；同一個編號以新讀到的為準（內政部偶爾會更正）"""
    hist = load(code)
    for x in rows:
        k = x.get('編號')
        r = slim(x, names) if k else None
        if r:
            hist[k] = r
    save(code, hist)
    return hist


def export(code, hist, fid_of):
    """依行政區輸出 data/h/*.js；回傳 {(行政區, 鍵): 'fid-分片'}，給明細檔標記「這一戶有歷次」"""
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.startswith(code + '-'):
            os.remove(os.path.join(OUT_DIR, f))
    by = {}
    for r in hist.values():
        by.setdefault((r[1], r[0]), []).append(r)
    files, marks = {}, {}
    for (dist, key), lst in by.items():
        if len(lst) < 2 or dist not in fid_of or key.startswith('|'):
            continue
        lst.sort(key=lambda r: r[2], reverse=True)
        shard = f'{fid_of[dist]}-{zlib.crc32(key.encode("utf-8")) % SHARDS}'
        files.setdefault(shard, {})[key] = [r[2:] for r in lst]   # [成交日, 型態, 總價, 單價, 建坪, 地坪, 移轉層次, 特殊]
        marks[(dist, key)] = shard
    for shard, data in files.items():
        with open(os.path.join(OUT_DIR, shard + '.js'), 'w', encoding='utf-8') as f:
            f.write('/* 自動產生，請勿手動修改 */\nwindow.RP_HIST&&RP_HIST(' + json.dumps(shard) + ',' +
                    json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ');\n')
    print(f'{code} 歷次：{len(marks)} 戶有兩次以上成交，{len(files)} 個檔')
    return marks


def backfill():
    """第一次建立累積檔：從 101S1 抓到最新一季（已經存在的季別資料會一起覆蓋）"""
    from build_regions import COUNTIES
    import datetime
    t = datetime.date.today()
    last = (t.year - 1911, (t.month - 1) // 3 + 1)
    for code, cname, names in COUNTIES:
        hist = load(code)
        y, q = FIRST_SEASON
        while (y, q) <= last:
            s = f'{y}S{q}'
            try:
                d = lvr.fetch_season(code, s)
            except Exception as e:
                print(f'{code} {s} 下載失敗：{e}')
                d = None
            if d:
                for x in d:
                    r = slim(x, names) if x.get('編號') else None
                    if r:
                        hist[x['編號']] = r
                print(f'{code} {s} {len(d)} 筆（累積 {len(hist)}）')
            q += 1
            if q == 5:
                y, q = y + 1, 1
        save(code, hist)
        print(f'{cname} 完成：{len(hist)} 筆')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'backfill':
        backfill()
    else:
        print(__doc__)
