# -*- coding: utf-8 -*-
"""
周邊機能地點資料產生器（中彰投）
================================
給官網「物件詳情頁 → 周邊機能地圖」用。每月由 GitHub 機器人跑一次，訪客不會直接去查外部服務。

資料來源：
  - OpenStreetMap（經 Overpass API 取得）：所有地點的名稱與座標（ODbL 授權，需標示「© OpenStreetMap 貢獻者」）
  - 教育部統計處 各級學校名錄（政府資料開放授權條款第 1 版）：核對學校名稱、補上官方學校代碼；
    名錄裡找不到的國小／國中／高中職／大專（可能已廢校、改名或標錯）就不列出
  官方名錄只有地址、沒有座標，所以座標一律用 OpenStreetMap 的。

產出：
  data/poi/meta.json         取得時間、OSM 資料時間、各分類筆數、分類說明
  data/poi/{列}_{行}.json     依 0.05 度（約 5 公里）切格，網頁只下載物件附近的幾格

每一筆：[分類, 子類, 名稱, 緯度, 經度, 來源代碼, 核對]（核對＝moe 表示名稱與教育部名錄相符）
  分類：transit 交通 / school 學校 / park 公園 / medical 醫療 / shop 採買
  來源代碼：OSM 物件編號，例如 n123（點）、w456（線面）、r789（關聯）

用法：python tools/build_poi.py
"""
import csv, io, json, math, os, re, sys, time, datetime, urllib.request, urllib.parse

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'poi')
GRID = 0.05
# 中彰投範圍（含一點縣界外，邊界附近的物件才查得到隔壁縣市的設施）
SOUTH, WEST, NORTH, EAST = 23.42, 120.20, 24.46, 121.46
TILE = 0.26                       # 每次向 Overpass 查一塊，避免單次查詢太大
ENDPOINTS = ['https://overpass-api.de/api/interpreter',                 # 主要
             'https://maps.mail.ru/osm/tools/overpass/api/interpreter']  # 備用
UA = 'anna-house-poi/1.0 (+https://github.com/k10108024-del/anna-realprice)'

MOE = {   # 教育部統計處 各級學校名錄（data.gov.tw 6087／6088／6089／6091）
    '國小': 'https://stats.moe.gov.tw/files/school/{y}/e1_new.csv',
    '國中': 'https://stats.moe.gov.tw/files/opendata/j1_new.csv',
    '高中職': 'https://stats.moe.gov.tw/files/school/{y}/high.csv',
    '大專院校': 'https://stats.moe.gov.tw/files/opendata/u1_new.csv',
}

QUERY = """[out:json][timeout:240][bbox:{s},{w},{n},{e}];
(
  nwr["railway"~"^(station|halt)$"]["name"];
  node["highway"="bus_stop"]["name"];
  node["public_transport"="platform"]["bus"="yes"]["name"];
  nwr["amenity"~"^(school|kindergarten|university|college|hospital|clinic|doctors|pharmacy|marketplace)$"]["name"];
  nwr["shop"~"^(convenience|supermarket|wholesale)$"]["name"];
  nwr["leisure"="park"]["name"];
);
out center tags qt;"""


try:                                   # 有 certifi 就用它的憑證（部分電腦內建憑證過期）
    import ssl, certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = None


def http(url, data=None, timeout=300):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


def overpass(s, w, n, e):
    body = urllib.parse.urlencode({'data': QUERY.format(s=s, w=w, n=n, e=e)}).encode()
    last = None
    for attempt in range(4):                     # 有限次重試，失敗換備用伺服器
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            d = json.loads(http(url, body))
            if d.get('remark') and 'error' in d['remark'].lower():
                raise RuntimeError(d['remark'][:200])
            return d
        except Exception as ex:
            last = ex
            print(f'  重試 {attempt + 1}：{url.split("/")[2]} {str(ex)[:120]}')
            time.sleep(45 * (attempt + 1))
    raise RuntimeError(f'Overpass 查詢失敗：{last}')


# ---------- 教育部學校名錄 ----------
def norm_school(name):
    """把「臺中市立○○國民小學」「縣立○○國小」「○○國小」都變成「○○國小」再比對。"""
    n = name.replace('臺', '台').replace(' ', '').replace('　', '')
    n = re.sub(r'國[（(]中[)）]小|國中[（(]小[)）]|國民中小學|中小學$', '國中小', n)   # 教育部寫「國(中)小」，OSM 寫「國中小」
    n = re.sub(r'[（(].*?[)）]', '', n)
    n = re.sub(r'^(國立|私立|市立|縣立|台中市立|台中市私立|台中市|彰化縣立|彰化縣私立|彰化縣|南投縣立|南投縣私立|南投縣|'
               r'台中市.{1,3}區|彰化縣.{1,3}[鄉鎮市]|南投縣.{1,3}[鄉鎮市])+', '', n)
    n = re.sub(r'^.{1,3}[區鄉鎮市]立', '', n)   # 例：草屯鎮立
    for a, b in (('國民小學', '國小'), ('國民中學', '國中'), ('附設國民小學', '附設國小'),
                 ('高級中學', '高中'), ('高級中等學校', '高中'), ('高級工業職業學校', '高工'),
                 ('高級商工職業學校', '商工'), ('高級農工職業學校', '農工'), ('高級商業職業學校', '高商'),
                 ('高級家事商業職業學校', '家商'), ('高級職業學校', '高職')):
        n = n.replace(a, b)
    n = re.sub(r'(雙語|國際|實驗)?小學$', '國小', n) if not n.endswith('國小') else n   # 華盛頓雙語小學 → 華盛頓國小
    return n


def school_keys(name):
    """一所學校可能的比對名稱：原名、去掉開頭行政區（教育部有「北屯區大坑國小」這種寫法）、去掉分校／分班。"""
    n = norm_school(name)
    n = re.sub(r'^(天主教|基督教|財團法人|私立)+', '', n)
    n = n.replace('女子高中', '女中').replace('女子中學', '女中')
    keys = {n}
    m = re.match(r'^.{1,3}[區鄉鎮](.{2,}(國小|國中|國中小|高中|中學))$', n)
    if m:
        keys.add(m.group(1))
    # 去掉分校、校區、分部（教育部名錄只列本校）
    keys.add(re.sub(r'(國小|國中|國中小|高中|中學|大學|學院)[^國大]{1,10}(分校|分班|分部|校區)$', r'\1', n))
    # 私校常「中學／高中」混用
    for k in list(keys):
        if k.endswith('中學'):
            keys.add(k[:-2] + '高中')
        elif k.endswith('高中'):
            keys.add(k[:-2] + '中學')
    return keys


def load_moe():
    """回傳 {正規化名稱: (子類, 代碼, 官方名稱, 縣市)}，只留中彰投（含鄰近縣市，邊界用）。"""
    year = datetime.date.today().year - 1911 - (0 if datetime.date.today().month >= 8 else 1)
    out, used = {}, {}
    for sub, tmpl in MOE.items():
        raw = None
        for y in (year, year - 1, year - 2):
            try:
                raw = http(tmpl.format(y=y), timeout=120); used[sub] = y if '{y}' in tmpl else '最新'; break
            except Exception as ex:
                print(f'  教育部 {sub} {y} 學年讀取失敗：{ex}')
        if not raw:
            raise RuntimeError(f'教育部 {sub} 名錄讀不到')
        rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        latest = max(int(r['學年度']) for r in rows if r.get('學年度', '').isdigit())
        for r in rows:
            if r.get('學年度') != str(latest):
                continue
            if not any(c in r.get('縣市名稱', '') for c in ('臺中', '台中', '彰化', '南投', '雲林', '苗栗', '嘉義', '花蓮')):
                continue
            for k in school_keys(r['學校名稱']):
                out.setdefault(k, (sub, r['代碼'], r['學校名稱'], r['縣市名稱']))
        used[sub] = latest
    return out, used


# ---------- 分類 ----------
BAD_SCHOOL = re.compile(r'補習|駕訓|駕駛|才藝|安親|美語|英語|英文|音樂|舞蹈|咖啡|烘焙|課後|文理|數學|電腦|托嬰|托育|美容|美髮|游泳|'
                        r'跆拳|圍棋|書法|珠心算|作文|潛能|升學|教室|家教|社區大學|長青|樂齡|老人|駕|汽車|機車|宗教|神學|佛學|聖經')
BAD_MED = re.compile(r'動物|寵物|獸醫|犬|貓|美甲|美睫|SPA|按摩|養生館|月子|醫療用品|醫療器材|醫材|中藥行|蔘藥|青草')   # 醫療用品店、中藥行不算藥局
CVS = re.compile(r'7-?ELEVEN|7-?11|統一超商|全家|FamilyMart|萊爾富|Hi-?Life|OK超商|OK・?mart|OKmart|來來超商', re.I)
SUPER = re.compile(r'全聯|美廉社|楓康|家樂福|大潤發|愛買|好市多|Costco|頂好|惠康|Simple ?Mart|超市|超級市場|生鮮|量販', re.I)
HYPER = re.compile(r'家樂福|大潤發|愛買|好市多|Costco|量販', re.I)
BAD_PARK = re.compile(r'停車|公墓|墓園|納骨|殯|工業區|工業園區|科學園區|軟體園區|產業園區|加工區|農場|露營')


def school_kind(name, t):
    if BAD_SCHOOL.search(name) or re.search(r'補校|進修', name):
        return None
    if re.search(r'幼兒園|幼稚園|附幼', name):
        return '幼兒園'
    if re.search(r'國民中小學|國中小|中小學', name):
        return '國中小'
    if re.search(r'國小|國民小學|小學', name):
        return '國小'
    if re.search(r'國中|國民中學', name):
        return '國中'
    # 高中職要先判斷：「○○大學附屬高中」「師大附屬高工」是高中職，不是大學
    if re.search(r'附屬高|附中|高級.*職業學校|高中|高級中|高職|高工|高商|高農|商工|家商|農工|工商|中學|實驗學校|特殊教育學校|啟智|啟明|啟聰', name):
        return '高中職'
    if re.search(r'大學|技術學院|專科學校|醫學院|管理學院|護理.*學校', name):
        return '大專院校'
    if t.get('amenity') == 'kindergarten':
        return '幼兒園' if re.search(r'幼', name) else None
    return None


def classify(e, moe):
    t = e.get('tags', {})
    name = (t.get('name:zh-Hant') or t.get('name:zh') or t.get('name') or '').strip()
    if not name or t.get('disused') or t.get('abandoned') or t.get('railway:historic'):
        return None
    if re.search(r'歇業|停業|已拆|已關|關閉|已遷|遷校|廢校|舊址|舊校區', name) or name in ('夜市', '市場', '公園', '公車站', '亭子', '涼亭', '綠地', '廣場', '兒童遊戲場'):
        return None   # 名稱寫明已關閉／搬遷，或只有通稱沒有名字
    am, shop = t.get('amenity'), t.get('shop')
    if t.get('railway') in ('station', 'halt'):
        org = t.get('network', '') + '|' + t.get('operator', '')
        if '捷運' in org:
            return ('transit', '捷運站', name if name.endswith('站') else name + '站', None)
        if '高鐵' in org or '高速鐵路' in org:
            return ('transit', '高鐵站', name if '高鐵' in name else '高鐵' + name + '站', None)
        if '臺鐵' in org or '台鐵' in org or '臺灣鐵路' in org or '台灣鐵路' in org:
            return ('transit', '火車站', name if name.endswith('站') else name + '車站', None)
        return None
    if t.get('highway') == 'bus_stop' or (t.get('public_transport') == 'platform' and t.get('bus') == 'yes'):
        return ('transit', '公車站', name, None)
    if am in ('school', 'kindergarten', 'university', 'college'):
        k = school_kind(name, t)
        if not k:
            return None
        if re.search(r'特殊教育學校|啟聰|啟明|啟智', name):   # 特教學校在另一份名錄，不核對但照列
            return ('school', '特殊教育學校', name, None)
        if k in ('國小', '國中', '國中小', '高中職', '大專院校'):
            hit = next((moe[k] for k in school_keys(name) if k in moe), None)
            if not hit:
                return ('_unmatched', k, name, None)
            # 同名學校各縣市都有（例如光華國小），名錄沒有座標無法確定是哪一所，所以只記「名稱核對過」，不放官方代碼
            return ('school', k, name, 'moe')
        return ('school', k, name, None)
    if am in ('hospital', 'clinic', 'doctors', 'pharmacy'):
        if BAD_MED.search(name):
            return None
        if am == 'hospital':
            return ('medical', '醫院', name, None)
        if am == 'pharmacy':
            return ('medical', '藥局', name, None)
        return ('medical', '診所', name, None)
    if am == 'marketplace':
        return ('shop', '夜市' if '夜市' in name else '市場', name, None)
    if shop == 'convenience':
        brand = t.get('brand', '') + ' ' + name
        return ('shop', '超商', name, None) if CVS.search(brand) else None
    if shop in ('supermarket', 'wholesale'):
        brand = t.get('brand', '') + ' ' + name
        if HYPER.search(brand):
            return ('shop', '量販店', name, None)
        return ('shop', '超市', name, None) if SUPER.search(brand) else None
    if t.get('leisure') == 'park':
        return None if BAD_PARK.search(name) else ('park', '公園', name, None)
    return None


def dist_m(a, b):
    dy = (a[0] - b[0]) * 111320
    dx = (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def main():
    os.makedirs(OUT, exist_ok=True)
    fetched = datetime.datetime.now(datetime.timezone.utc)
    print('讀取教育部學校名錄…')
    moe, moe_years = load_moe()
    print(f'  名錄 {len(moe)} 校，學年度 {moe_years}')

    elements, osm_base = {}, ''
    cache = os.environ.get('POI_CACHE')          # 本機測試用：把下載結果存起來，改分類規則時不必重抓
    if cache and os.path.exists(cache):
        c = json.load(open(cache, encoding='utf-8'))
        elements, osm_base = c['elements'], c['osm_base']
        print(f'  使用本機快取 {len(elements)} 筆')
    lat = NORTH if elements else SOUTH
    while lat < NORTH:
        lng = WEST
        while lng < EAST:
            s, w, n, e = round(lat, 3), round(lng, 3), round(min(lat + TILE, NORTH), 3), round(min(lng + TILE, EAST), 3)
            d = overpass(s, w, n, e)
            osm_base = max(osm_base, d.get('osm3s', {}).get('timestamp_osm_base', ''))
            for x in d.get('elements', []):
                elements[x['type'][0] + str(x['id'])] = x
            print(f'  {s},{w} → {len(d.get("elements", []))} 筆（累計 {len(elements)}）')
            time.sleep(25)                        # 對公用伺服器客氣一點（太密集會被回 429）
            lng += TILE
        lat += TILE

    if cache and not os.path.exists(cache):
        json.dump({'elements': elements, 'osm_base': osm_base}, open(cache, 'w', encoding='utf-8'), ensure_ascii=False)

    items, unmatched = [], []
    for oid, x in elements.items():
        c = classify(x, moe)
        if not c:
            continue
        y = x.get('lat') or x.get('center', {}).get('lat')
        xx = x.get('lon') or x.get('center', {}).get('lon')
        if y is None or xx is None:
            continue
        if c[0] == '_unmatched':
            unmatched.append(f'{c[1]} {c[2]} {oid}')
            continue
        items.append({'c': c[0], 's': c[1], 'n': c[2], 'p': (round(y, 5), round(xx, 5)), 'o': oid, 'k': c[3],
                      'area': oid[0] != 'n'})

    # 去重：同分類、同名、距離很近的視為同一個地點（OSM 常同時有「點」和「範圍」）
    # 公車站只合併幾乎重疊（30 公尺內）的站牌，不同方向的站牌保留，網頁再依同名分組顯示
    items.sort(key=lambda r: (not r['area'], r['o']))   # 範圍（學校、公園的整塊地）優先保留
    kept, seen = [], {}
    for r in items:
        key = (r['c'], r['n'].replace(' ', ''))
        lim = 30 if r['s'] == '公車站' else (400 if r['c'] in ('school', 'park') else 150)
        if any(dist_m(r['p'], q) < lim for q in seen.get(key, [])):
            continue
        # 不同校區、分校名稱不同，會各自保留
        seen.setdefault(key, []).append(r['p'])
        kept.append(r)

    tiles, counts = {}, {}
    for r in kept:
        iy, ix = int(math.floor(r['p'][0] / GRID)), int(math.floor(r['p'][1] / GRID))
        tiles.setdefault(f'{iy}_{ix}', []).append([r['c'], r['s'], r['n'], r['p'][0], r['p'][1], r['o'], r['k'] or ''])
        counts[r['s']] = counts.get(r['s'], 0) + 1

    # 舊格子先清掉（範圍內沒資料的格子不留舊檔）
    for f in os.listdir(OUT):
        if re.match(r'^-?\d+_-?\d+\.json$', f):
            os.remove(os.path.join(OUT, f))
    for k, v in tiles.items():
        v.sort(key=lambda r: (r[0], r[1], r[2]))
        with open(os.path.join(OUT, k + '.json'), 'w', encoding='utf-8') as f:
            json.dump(v, f, ensure_ascii=False, separators=(',', ':'))

    meta = {
        'fetchedAt': fetched.strftime('%Y-%m-%dT%H:%MZ'),       # 我們取得資料的時間
        'osmBase': osm_base,                                     # OpenStreetMap 資料本身的時間
        'moeYears': moe_years,                                   # 教育部名錄學年度
        'grid': GRID,
        'bbox': [SOUTH, WEST, NORTH, EAST],
        'counts': counts,
        'tiles': sorted(tiles),
    }
    with open(os.path.join(OUT, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, 'unmatched_schools.txt'), 'w', encoding='utf-8') as f:
        f.write('# OSM 有、教育部名錄比對不到而未列出的學校（供人工檢查名稱比對規則）\n' + '\n'.join(sorted(unmatched)) + '\n')
    print(f'完成：{len(kept)} 個地點、{len(tiles)} 格；未比對到名錄的學校 {len(unmatched)} 筆')
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == '__main__':
    main()
