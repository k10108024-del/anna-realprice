# -*- coding: utf-8 -*-
"""
門牌整理（共用）：實價登錄的門牌 → 去掉縣市、鄉鎮市區、里鄰，全形改半形，樓層改阿拉伯數字，地政造字拿掉
======================================================
【2026-11-01】原本官網歷次（build_history.py）和草屯門牌比對（草屯實價比對/tools/build.py）各寫一份，
官網那份少了 10-22 的修正（一層層剝縣市鄉鎮、開頭只有里），同一戶可能被拆成兩戶 → 統一用這一份。
以後改門牌規則只改這裡；改完官網歷次要重跑 python tools/build_history.py backfill，D1 lvr-db 要重新匯入。
"""
import re

from build_home import FW, cn_num

CN_FLOOR = re.compile(r'([一二三四五六七八九十]+)樓')


def safe_cn(s):
    """中文數字轉阿拉伯數字；遇到不正常的（例：台中預售屋有「三八樓」）回傳 None，保留原文"""
    try:
        return cn_num(s)
    except (KeyError, ValueError):
        return None


COUNTY_NAMES = ('南投縣', '彰化縣', '臺中市', '台中市', '臺中縣', '台中縣')
# 中彰投所有鄉鎮市區＋舊名（員林鎮 2015 改制員林市）。門牌開頭是這些就拿掉——
# 實價登錄常有「行政區填北區、門牌寫北屯區…」這種不一致，只拿掉自己的鄉鎮會漏（2026-10-22 修正）
TOWN_NAMES = sorted('''中區 東區 西區 南區 北區 北屯區 西屯區 南屯區 太平區 大里區 霧峰區 烏日區 豐原區 后里區 石岡區 東勢區 和平區
新社區 潭子區 大雅區 神岡區 大肚區 沙鹿區 龍井區 梧棲區 清水區 大甲區 外埔區 大安區
彰化市 鹿港鎮 和美鎮 線西鄉 伸港鄉 福興鄉 秀水鄉 花壇鄉 芬園鄉 員林市 員林鎮 溪湖鎮 田中鎮 大村鄉 埔鹽鄉 埔心鄉 永靖鄉
社頭鄉 二水鄉 北斗鎮 二林鎮 田尾鄉 埤頭鄉 芳苑鄉 大城鄉 竹塘鄉 溪州鄉
南投市 埔里鎮 草屯鎮 竹山鎮 集集鎮 名間鄉 鹿谷鄉 中寮鄉 魚池鄉 國姓鄉 水里鄉 信義鄉 仁愛鄉'''.split(), key=len, reverse=True)


def clean_addr(a, town=''):
    """去掉縣市、鄉鎮市區、里鄰，全形數字改半形，樓層改阿拉伯數字，地政造字拿掉
    【修正 2026-10-19】原本只去掉「南投縣」「草屯鎮」（當初只做草屯）；彰化、台中、南投其他鄉鎮的門牌九成帶縣市鄉鎮 →
    開頭的縣市名、以及這筆自己的鄉鎮（town）也拿掉"""
    a = (a or '').translate(FW).replace('巿', '市')
    for n in ('南投縣', '草屯鎮'):
        a = a.replace(n, '')
    a = a.strip()
    prev = None
    while prev != a:   # 「彰化縣員林市…」「北斗鎮彰化縣埤頭鄉…」這種疊好幾層的，一層一層剝
        prev = a
        for n in COUNTY_NAMES + tuple(TOWN_NAMES) + ((town,) if town else ()):
            if a.startswith(n):
                a = a[len(n):].strip()
                break
    a = re.sub(r'[^\s路街道巷段]{1,4}里\d+鄰', '', a)
    a = re.sub(r'\d+鄰', '', a)
    a = re.sub(r'^[^\d路街道巷段]{1,3}里(?=[^\d段])', '', a)   # 開頭只有里、沒有鄰，例如「新厝里新富二街」；後面接「段」的是地段名（埔里段…），不能拿掉（2026-11-01 修正）
    a = re.sub('[-]', '', a)
    a = CN_FLOOR.sub(lambda m: f'{safe_cn(m.group(1)) or m.group(1)}樓', a)
    return re.sub(r'\s+', '', a)
