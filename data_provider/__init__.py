# -*- coding: utf-8 -*-
"""
===================================
數據源策略層 - 包初始化
===================================

本包實現策略模式管理多個數據源，實現：
1. 統一的數據獲取接口
2. 自動故障切換
3. 防封禁流控策略

數據源優先級（動態調整）：
0. FinMindFetcher (Priority -1) - 🔥 台股最高優先級，來自 FinMind API
1. EfinanceFetcher (Priority 0) - 來自 efinance 庫
2. AkshareFetcher (Priority 1) - 來自 akshare 庫
3. PytdxFetcher (Priority 2) - 來自 pytdx 庫（通達信）
4. TushareFetcher (Priority 2) - 來自 tushare 庫（配置 Token 後提升為 Priority 0）
5. BaostockFetcher (Priority 3) - 來自 baostock 庫
6. YfinanceFetcher (Priority 4) - 來自 yfinance 庫

提示：優先級數字越小越優先，同優先級按初始化順序排列
"""

from .base import BaseFetcher, DataFetcherManager
from .finmind_fetcher import FinMindFetcher
from .efinance_fetcher import EfinanceFetcher
from .akshare_fetcher import AkshareFetcher
from .tushare_fetcher import TushareFetcher
from .pytdx_fetcher import PytdxFetcher
from .baostock_fetcher import BaostockFetcher
from .yfinance_fetcher import YfinanceFetcher

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'FinMindFetcher',
    'EfinanceFetcher',
    'AkshareFetcher',
    'TushareFetcher',
    'PytdxFetcher',
    'BaostockFetcher',
    'YfinanceFetcher',
]
