# -*- coding: utf-8 -*-
"""
===================================
FinMindFetcher - 台股專業數據源 (Priority -1)
===================================

數據來源：FinMind API（https://finmindtrade.com/）
特點：台股專業數據源，提供豐富的台股數據
定位：台股最優先數據源，數據最詳細

數據類型：
1. 日線行情數據：開高低收、成交量、成交額
2. 籌碼面數據：融資融券、外資買賣超、主力進出
3. 基本面數據：財報、股利、月營收
4. 技術指標：本益比、殖利率等

關鍵策略：
1. 自動處理台股代碼格式（去除 .TW 後綴）
2. API 頻率限制：免費 300次/小時，註冊 600次/小時
3. 失敗後自動降級到 YFinance
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS

logger = logging.getLogger(__name__)


class FinMindFetcher(BaseFetcher):
    """
    FinMind API 數據源實現

    優先級：-1（最高，台股專用數據源）
    數據來源：FinMind API

    關鍵特性：
    - 專為台股設計，數據最詳細
    - 支援籌碼面數據（融資融券、外資買賣超）
    - 支援基本面數據（財報、股利、營收）
    - 需要註冊獲取 API Token

    API 限制：
    - 免費用戶：300 requests/hour
    - 註冊用戶：600 requests/hour

    官方文檔：https://finmind.github.io/
    """

    name = "FinMindFetcher"
    priority = -1  # 最高優先級，台股首選

    def __init__(self, api_token: Optional[str] = None):
        """
        初始化 FinMindFetcher

        Args:
            api_token: FinMind API Token（可選，有 token 可提升請求限額）
        """
        self.api_token = api_token
        self._api = None
        self._is_available = False

        try:
            from FinMind.data import DataLoader
            self._api = DataLoader()

            # 如果提供了 token，則登入
            if self.api_token:
                self._api.login_by_token(api_token=self.api_token)
                logger.info("✅ FinMind API 已登入（註冊用戶，600次/小時）")
                self._is_available = True
            else:
                logger.warning("⚠️  未配置 FINMIND_API_TOKEN，使用訪客模式（300次/小時）")
                logger.warning("    建議前往 https://finmindtrade.com/ 註冊獲取免費 Token")
                self._is_available = True  # 訪客模式也可用

        except ImportError:
            logger.error("❌ 未安裝 FinMind 套件，請執行: pip install finmind")
            self._is_available = False
        except Exception as e:
            logger.error(f"❌ FinMind 初始化失敗: {e}")
            self._is_available = False

    def _normalize_stock_code(self, stock_code: str) -> str:
        """
        標準化股票代碼為 FinMind 格式

        FinMind 台股代碼格式：純數字，如 '2330', '2317'

        Args:
            stock_code: 原始代碼，可能包含 .TW 後綴

        Returns:
            FinMind 格式代碼（純數字）
        """
        code = stock_code.strip().upper()

        # 去除 .TW 或 .TWO 後綴
        if code.endswith('.TW') or code.endswith('.TWO'):
            code = code.replace('.TW', '').replace('.TWO', '')

        # 檢查是否為純數字（台股代碼）
        if not code.isdigit():
            raise DataFetchError(f"FinMind 僅支援台股，代碼 {stock_code} 不是有效的台股代碼")

        # 台股代碼通常是 4 位數字
        if len(code) != 4:
            logger.warning(f"代碼 {code} 長度不是 4 位，可能不是標準台股代碼")

        return code

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        從 FinMind API 獲取原始數據

        使用 taiwan_stock_daily() 獲取台股日線數據

        流程：
        1. 檢查 API 是否可用
        2. 標準化股票代碼
        3. 調用 FinMind API
        4. 處理返回數據

        Args:
            stock_code: 股票代碼
            start_date: 開始日期
            end_date: 結束日期

        Returns:
            原始數據 DataFrame
        """
        if not self._is_available:
            raise DataFetchError("FinMind API 不可用")

        # 標準化代碼
        finmind_code = self._normalize_stock_code(stock_code)

        logger.debug(f"調用 FinMind API: taiwan_stock_daily({finmind_code}, {start_date}, {end_date})")

        try:
            # 調用 FinMind API 獲取台股日線數據
            df = self._api.taiwan_stock_daily(
                stock_id=finmind_code,
                start_date=start_date,
                end_date=end_date
            )

            if df is None or df.empty:
                raise DataFetchError(f"FinMind 未查詢到 {stock_code} 的數據")

            logger.info(f"✅ FinMind 成功獲取 {stock_code} 數據，共 {len(df)} 條")
            return df

        except AttributeError as e:
            raise DataFetchError(f"FinMind API 方法調用失敗，請檢查套件版本: {e}") from e
        except Exception as e:
            if "Rate limit" in str(e) or "429" in str(e):
                raise DataFetchError(f"FinMind API 頻率限制（{self._get_rate_limit_msg()}），請稍後重試") from e
            raise DataFetchError(f"FinMind 獲取數據失敗: {e}") from e

    def _get_rate_limit_msg(self) -> str:
        """獲取頻率限制提示信息"""
        if self.api_token:
            return "註冊用戶 600次/小時"
        return "訪客模式 300次/小時，建議註冊提升限額"

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        標準化 FinMind 數據

        FinMind 返回的列名：
        - date: 日期
        - stock_id: 股票代碼
        - Trading_Volume: 成交股數
        - Trading_money: 成交金額
        - open: 開盤價
        - max: 最高價
        - min: 最低價
        - close: 收盤價
        - spread: 漲跌價差
        - Trading_turnover: 成交筆數

        需要映射到標準列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()

        # 列名映射（FinMind 使用不同的列名）
        column_mapping = {
            'date': 'date',
            'open': 'open',
            'max': 'high',      # FinMind 使用 max 表示最高價
            'min': 'low',       # FinMind 使用 min 表示最低價
            'close': 'close',
            'Trading_Volume': 'volume',    # 成交股數
            'Trading_money': 'amount',     # 成交金額
        }

        # 檢查必要的列是否存在
        missing_cols = [col for col in column_mapping.keys() if col not in df.columns]
        if missing_cols:
            logger.warning(f"FinMind 數據缺少列: {missing_cols}")

        # 重命名列
        df = df.rename(columns=column_mapping)

        # 計算漲跌幅（如果 FinMind 沒有提供）
        if 'pct_chg' not in df.columns and 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)

        # 確保 volume 和 amount 是數值類型
        for col in ['volume', 'amount']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # 添加股票代碼列（保留原始格式，如 2330.TW）
        df['code'] = stock_code

        # 確保日期格式正確
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]

        # 按日期排序
        if 'date' in df.columns:
            df = df.sort_values('date')

        return df

    def get_chip_data(self, stock_code: str) -> Optional[dict]:
        """
        獲取籌碼面數據（台股特有功能）

        包括：
        - 融資融券餘額
        - 外資持股
        - 主力進出

        Args:
            stock_code: 股票代碼

        Returns:
            籌碼數據字典，失敗返回 None
        """
        if not self._is_available:
            return None

        try:
            finmind_code = self._normalize_stock_code(stock_code)
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

            chip_data = {}

            # 1. 獲取融資融券數據
            try:
                margin_df = self._api.taiwan_stock_margin_purchase_short_sale(
                    stock_id=finmind_code,
                    start_date=start_date,
                    end_date=end_date
                )
                if not margin_df.empty:
                    latest = margin_df.iloc[-1]
                    chip_data['margin_purchase'] = float(latest.get('MarginPurchaseBuy', 0))
                    chip_data['short_sale'] = float(latest.get('ShortSaleBuy', 0))
            except Exception as e:
                logger.warning(f"獲取融資融券數據失敗: {e}")

            # 2. 獲取外資買賣超
            try:
                institutional_df = self._api.taiwan_stock_institutional_investors(
                    stock_id=finmind_code,
                    start_date=start_date,
                    end_date=end_date
                )
                if not institutional_df.empty:
                    latest = institutional_df[institutional_df['name'] == 'Foreign_Investor']
                    if not latest.empty:
                        chip_data['foreign_buy'] = float(latest.iloc[-1].get('buy', 0))
                        chip_data['foreign_sell'] = float(latest.iloc[-1].get('sell', 0))
                        chip_data['foreign_net'] = chip_data['foreign_buy'] - chip_data['foreign_sell']
            except Exception as e:
                logger.warning(f"獲取外資數據失敗: {e}")

            return chip_data if chip_data else None

        except Exception as e:
            logger.error(f"獲取籌碼數據失敗: {e}")
            return None


if __name__ == "__main__":
    # 測試代碼
    logging.basicConfig(level=logging.DEBUG)

    # 測試不帶 token
    fetcher = FinMindFetcher()

    try:
        df = fetcher.get_daily_data('2330.TW', days=30)  # 台積電
        print(f"✅ 獲取成功，共 {len(df)} 條數據")
        print(df.tail())

        # 測試籌碼數據
        chip_data = fetcher.get_chip_data('2330.TW')
        if chip_data:
            print("\n📊 籌碼數據:")
            for key, value in chip_data.items():
                print(f"  {key}: {value}")
    except Exception as e:
        print(f"❌ 獲取失敗: {e}")
