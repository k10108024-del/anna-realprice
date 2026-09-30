# -*- coding: utf-8 -*-
"""
實價登錄自動更新（GitHub 機器人每月 2、12、22 日執行，也可以手動執行）
  1. 下載內政部本期（最新一批）資料存起來
  2. 產生中彰投查詢資料 data/index.js、data/B-01.js…
  3. 產生首頁速報資料 data/data.js
用法：python tools/update.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import lvr, build_regions, build_home

lvr.save_current_batch(['B', 'N', 'M'])
lvr.prune_current()
build_regions.main()
build_home.main()
print('全部完成')
