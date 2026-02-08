# -*- coding: utf-8 -*-
"""
===================================
A股自選股智能分析系統 - 環境驗證測試
===================================

用於驗證 .env 配置是否正確，包括：
1. 配置加載測試
2. 數據庫查看
3. 數據源測試
4. LLM 調用測試
5. 通知推送測試

使用方法：
    python test_env.py              # 運行所有測試
    python test_env.py --db         # 僅查看數據庫
    python test_env.py --llm        # 僅測試 LLM
    python test_env.py --fetch      # 僅測試數據獲取
    python test_env.py --notify     # 僅測試通知

"""
import os
os.environ["http_proxy"] = "http://127.0.0.1:10809"
os.environ["https_proxy"] = "http://127.0.0.1:10809"

import argparse
import logging
import sys
from datetime import datetime, date, timedelta
from typing import Optional

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def print_header(title: str):
    """打印標題"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_section(title: str):
    """打印小節"""
    print(f"\n--- {title} ---")


def test_config():
    """測試配置加載"""
    print_header("1. 配置加載測試")
    
    from src.config import get_config
    config = get_config()
    
    print_section("基礎配置")
    print(f"  股票列表: {config.stock_list}")
    print(f"  數據庫路徑: {config.database_path}")
    print(f"  最大併發數: {config.max_workers}")
    print(f"  調試模式: {config.debug}")
    
    print_section("API 配置")
    print(f"  Tushare Token: {'已配置 ✓' if config.tushare_token else '未配置 ✗'}")
    if config.tushare_token:
        print(f"    Token 前8位: {config.tushare_token[:8]}...")
    
    print(f"  Gemini API Key: {'已配置 ✓' if config.gemini_api_key else '未配置 ✗'}")
    if config.gemini_api_key:
        print(f"    Key 前8位: {config.gemini_api_key[:8]}...")
    print(f"  Gemini 主模型: {config.gemini_model}")
    print(f"  Gemini 備選模型: {config.gemini_model_fallback}")
    
    print(f"  企業微信 Webhook: {'已配置 ✓' if config.wechat_webhook_url else '未配置 ✗'}")
    
    print_section("配置驗證")
    warnings = config.validate()
    if warnings:
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("  ✓ 所有配置項驗證通過")
    
    return True


def view_database():
    """查看數據庫內容"""
    print_header("2. 數據庫內容查看")
    
    from src.storage import get_db
    from sqlalchemy import text
    
    db = get_db()
    
    print_section("數據庫連接")
    print(f"  ✓ 連接成功")
    
    # 使用獨立的 session 查詢
    session = db.get_session()
    try:
        # 統計信息
        result = session.execute(text("""
            SELECT 
                code,
                COUNT(*) as count,
                MIN(date) as min_date,
                MAX(date) as max_date,
                data_source
            FROM stock_daily 
            GROUP BY code
            ORDER BY code
        """))
        stocks = result.fetchall()
        
        print_section(f"已存儲股票數據 (共 {len(stocks)} 只)")
        if stocks:
            print(f"  {'代碼':<10} {'記錄數':<8} {'起始日期':<12} {'最新日期':<12} {'數據源'}")
            print("  " + "-" * 60)
            for row in stocks:
                print(f"  {row[0]:<10} {row[1]:<8} {row[2]!s:<12} {row[3]!s:<12} {row[4] or 'Unknown'}")
        else:
            print("  暫無數據")
        
        # 查詢今日數據
        today = date.today()
        result = session.execute(text("""
            SELECT code, date, open, high, low, close, pct_chg, volume, ma5, ma10, ma20, volume_ratio
            FROM stock_daily 
            WHERE date = :today
            ORDER BY code
        """), {"today": today})
        today_data = result.fetchall()
        
        print_section(f"今日數據 ({today})")
        if today_data:
            for row in today_data:
                code, dt, open_, high, low, close, pct_chg, volume, ma5, ma10, ma20, vol_ratio = row
                print(f"\n  【{code}】")
                print(f"    開盤: {open_:.2f}  最高: {high:.2f}  最低: {low:.2f}  收盤: {close:.2f}")
                print(f"    漲跌幅: {pct_chg:.2f}%  成交量: {volume/10000:.2f}萬股")
                print(f"    MA5: {ma5:.2f}  MA10: {ma10:.2f}  MA20: {ma20:.2f}  量比: {vol_ratio:.2f}")
        else:
            print("  今日暫無數據")
        
        # 查詢最近10條數據
        result = session.execute(text("""
            SELECT code, date, close, pct_chg, volume, data_source
            FROM stock_daily 
            ORDER BY date DESC, code
            LIMIT 10
        """))
        recent = result.fetchall()
        
        print_section("最近10條記錄")
        if recent:
            print(f"  {'代碼':<10} {'日期':<12} {'收盤':<10} {'漲跌%':<8} {'成交量':<15} {'來源'}")
            print("  " + "-" * 70)
            for row in recent:
                vol_str = f"{row[4]/10000:.2f}萬" if row[4] else "N/A"
                print(f"  {row[0]:<10} {row[1]!s:<12} {row[2]:<10.2f} {row[3]:<8.2f} {vol_str:<15} {row[5] or 'Unknown'}")
    finally:
        session.close()
    
    return True


def test_data_fetch(stock_code: str = "600519"):
    """測試數據獲取"""
    print_header("3. 數據獲取測試")
    
    from data_provider import DataFetcherManager
    
    manager = DataFetcherManager()
    
    print_section("數據源列表")
    for i, name in enumerate(manager.available_fetchers, 1):
        print(f"  {i}. {name}")
    
    print_section(f"獲取 {stock_code} 數據")
    print(f"  正在獲取（可能需要幾秒鐘）...")
    
    try:
        df, source = manager.get_daily_data(stock_code, days=5)
        
        print(f"  ✓ 獲取成功")
        print(f"    數據源: {source}")
        print(f"    記錄數: {len(df)}")
        
        print_section("數據預覽（最近5條）")
        if not df.empty:
            preview_cols = ['date', 'open', 'high', 'low', 'close', 'pct_chg', 'volume']
            existing_cols = [c for c in preview_cols if c in df.columns]
            print(df[existing_cols].tail().to_string(index=False))
        
        return True
        
    except Exception as e:
        print(f"  ✗ 獲取失敗: {e}")
        return False


def test_llm():
    """測試 LLM 調用"""
    print_header("4. LLM (Gemini) 調用測試")
    
    from src.analyzer import GeminiAnalyzer
    from src.config import get_config
    import time
    
    config = get_config()
    
    print_section("模型配置")
    print(f"  主模型: {config.gemini_model}")
    print(f"  備選模型: {config.gemini_model_fallback}")
    
    # 檢查網絡連接
    print_section("網絡連接檢查")
    try:
        import socket
        socket.setdefaulttimeout(10)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("generativelanguage.googleapis.com", 443))
        print(f"  ✓ 可以連接到 Google API 服務器")
    except Exception as e:
        print(f"  ✗ 無法連接到 Google API 服務器: {e}")
        print(f"  提示: 請檢查網絡連接或配置代理")
        print(f"  提示: 可以設置環境變量 HTTPS_PROXY=http://your-proxy:port")
        return False
    
    analyzer = GeminiAnalyzer()
    
    print_section("模型初始化")
    if analyzer.is_available():
        print(f"  ✓ 模型初始化成功")
    else:
        print(f"  ✗ 模型初始化失敗（請檢查 API Key）")
        return False
    
    # 構造測試上下文
    test_context = {
        'code': '600519',
        'date': date.today().isoformat(),
        'today': {
            'open': 1420.0,
            'high': 1435.0,
            'low': 1415.0,
            'close': 1428.0,
            'volume': 5000000,
            'amount': 7140000000,
            'pct_chg': 0.56,
            'ma5': 1425.0,
            'ma10': 1418.0,
            'ma20': 1410.0,
            'volume_ratio': 1.1,
        },
        'ma_status': '多頭排列 📈',
        'volume_change_ratio': 1.05,
        'price_change_ratio': 0.56,
    }
    
    print_section("發送測試請求")
    print(f"  測試股票: 貴州茅臺 (600519)")
    print(f"  正在調用 Gemini API（超時: 60秒）...")
    
    start_time = time.time()
    
    try:
        result = analyzer.analyze(test_context)
        
        elapsed = time.time() - start_time
        print(f"\n  ✓ API 調用成功 (耗時: {elapsed:.2f}秒)")
        
        print_section("分析結果")
        print(f"  情緒評分: {result.sentiment_score}/100")
        print(f"  趨勢預測: {result.trend_prediction}")
        print(f"  操作建議: {result.operation_advice}")
        print(f"  技術分析: {result.technical_analysis[:80]}..." if len(result.technical_analysis) > 80 else f"  技術分析: {result.technical_analysis}")
        print(f"  消息面: {result.news_summary[:80]}..." if len(result.news_summary) > 80 else f"  消息面: {result.news_summary}")
        print(f"  綜合摘要: {result.analysis_summary}")
        
        if not result.success:
            print(f"\n  ⚠ 注意: {result.error_message}")
        
        return result.success
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ✗ API 調用失敗 (耗時: {elapsed:.2f}秒)")
        print(f"  錯誤: {e}")
        
        # 提供更詳細的錯誤提示
        error_str = str(e).lower()
        if 'timeout' in error_str or 'unavailable' in error_str:
            print(f"\n  診斷: 網絡超時，可能原因:")
            print(f"    1. 網絡不通（需要代理訪問 Google）")
            print(f"    2. API 服務暫時不可用")
            print(f"    3. 請求量過大被限流")
        elif 'invalid' in error_str or 'api key' in error_str:
            print(f"\n  診斷: API Key 可能無效")
        elif 'model' in error_str:
            print(f"\n  診斷: 模型名稱可能不正確，嘗試修改 .env 中的 GEMINI_MODEL")
        
        return False


def test_notification():
    """測試通知推送"""
    print_header("5. 通知推送測試")
    
    from src.notification import NotificationService
    from src.config import get_config
    
    config = get_config()
    service = NotificationService()
    
    print_section("配置檢查")
    if service.is_available():
        print(f"  ✓ 企業微信 Webhook 已配置")
        webhook_preview = config.wechat_webhook_url[:50] + "..." if len(config.wechat_webhook_url) > 50 else config.wechat_webhook_url
        print(f"    URL: {webhook_preview}")
    else:
        print(f"  ✗ 企業微信 Webhook 未配置")
        return False
    
    print_section("發送測試消息")
    
    test_message = f"""## 🧪 系統測試消息

這是一條來自 **A股自選股智能分析系統** 的測試消息。

- 測試時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 測試目的: 驗證企業微信 Webhook 配置

如果您收到此消息，說明通知功能配置正確 ✓"""
    
    print(f"  正在發送...")
    
    try:
        success = service.send_to_wechat(test_message)
        
        if success:
            print(f"  ✓ 消息發送成功，請檢查企業微信")
        else:
            print(f"  ✗ 消息發送失敗")
        
        return success
        
    except Exception as e:
        print(f"  ✗ 發送異常: {e}")
        return False


def run_all_tests():
    """運行所有測試"""
    print("\n" + "🚀" * 20)
    print("  A股自選股智能分析系統 - 環境驗證")
    print("  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("🚀" * 20)
    
    results = {}
    
    # 1. 配置測試
    try:
        results['配置加載'] = test_config()
    except Exception as e:
        print(f"  ✗ 配置測試失敗: {e}")
        results['配置加載'] = False
    
    # 2. 數據庫查看
    try:
        results['數據庫'] = view_database()
    except Exception as e:
        print(f"  ✗ 數據庫測試失敗: {e}")
        results['數據庫'] = False
    
    # 3. 數據獲取（跳過，避免太慢）
    # results['數據獲取'] = test_data_fetch()
    
    # 4. LLM 測試（可選）
    # results['LLM調用'] = test_llm()
    
    # 彙總
    print_header("測試結果彙總")
    for name, passed in results.items():
        status = "✓ 通過" if passed else "✗ 失敗"
        print(f"  {status}: {name}")
    
    print(f"\n提示: 使用 --llm 參數單獨測試 LLM 調用")
    print(f"提示: 使用 --fetch 參數單獨測試數據獲取")
    print(f"提示: 使用 --notify 參數單獨測試通知推送")


def query_stock_data(stock_code: str, days: int = 10):
    """查詢指定股票的數據"""
    print_header(f"查詢股票數據: {stock_code}")
    
    from src.storage import get_db
    from sqlalchemy import text
    
    db = get_db()
    
    session = db.get_session()
    try:
        result = session.execute(text("""
            SELECT date, open, high, low, close, pct_chg, volume, amount, ma5, ma10, ma20, volume_ratio
            FROM stock_daily 
            WHERE code = :code
            ORDER BY date DESC
            LIMIT :limit
        """), {"code": stock_code, "limit": days})
        
        rows = result.fetchall()
        
        if rows:
            print(f"\n  最近 {len(rows)} 條記錄:\n")
            print(f"  {'日期':<12} {'開盤':<10} {'最高':<10} {'最低':<10} {'收盤':<10} {'漲跌%':<8} {'MA5':<10} {'MA10':<10} {'量比':<8}")
            print("  " + "-" * 100)
            for row in rows:
                dt, open_, high, low, close, pct_chg, vol, amt, ma5, ma10, ma20, vol_ratio = row
                print(f"  {dt!s:<12} {open_:<10.2f} {high:<10.2f} {low:<10.2f} {close:<10.2f} {pct_chg:<8.2f} {ma5:<10.2f} {ma10:<10.2f} {vol_ratio:<8.2f}")
        else:
            print(f"  未找到 {stock_code} 的數據")
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description='A股自選股智能分析系統 - 環境驗證測試',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument('--db', action='store_true', help='查看數據庫內容')
    parser.add_argument('--llm', action='store_true', help='測試 LLM 調用')
    parser.add_argument('--fetch', action='store_true', help='測試數據獲取')
    parser.add_argument('--notify', action='store_true', help='測試通知推送')
    parser.add_argument('--config', action='store_true', help='查看配置')
    parser.add_argument('--stock', type=str, help='查詢指定股票數據，如 --stock 600519')
    parser.add_argument('--all', action='store_true', help='運行所有測試（包括 LLM）')
    
    args = parser.parse_args()
    
    # 如果沒有指定任何參數，運行基礎測試
    if not any([args.db, args.llm, args.fetch, args.notify, args.config, args.stock, args.all]):
        run_all_tests()
        return 0
    
    # 根據參數運行指定測試
    if args.config:
        test_config()
    
    if args.db:
        view_database()
    
    if args.stock:
        query_stock_data(args.stock)
    
    if args.fetch:
        test_data_fetch()
    
    if args.llm:
        test_llm()
    
    if args.notify:
        test_notification()
    
    if args.all:
        test_config()
        view_database()
        test_data_fetch()
        test_llm()
        test_notification()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
