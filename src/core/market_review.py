# -*- coding: utf-8 -*-
"""
===================================
台股自選股智能分析系統 - 台股覆盤模組
===================================

職責：
1. 執行台股覆盤分析
2. 生成覆盤報告
3. 保存和發送覆盤報告
"""

import logging
from datetime import datetime
from typing import Optional

from src.notification import NotificationService
from src.market_analyzer import MarketAnalyzer
from src.search_service import SearchService
from src.analyzer import GeminiAnalyzer


logger = logging.getLogger(__name__)


def run_market_review(
    notifier: NotificationService, 
    analyzer: Optional[GeminiAnalyzer] = None, 
    search_service: Optional[SearchService] = None,
    send_notification: bool = True
) -> Optional[str]:
    """
    執行台股覆盤分析

    Args:
        notifier: 通知服務
        analyzer: AI分析器（可選）
        search_service: 搜索服務（可選）
        send_notification: 是否發送通知

    Returns:
        覆盤報告文本
    """
    logger.info("開始執行台股覆盤分析...")
    
    try:
        market_analyzer = MarketAnalyzer(
            search_service=search_service,
            analyzer=analyzer
        )
        
        # 执行复盘
        review_report = market_analyzer.run_daily_review()
        
        if review_report:
            # 保存報告到文件
            date_str = datetime.now().strftime('%Y%m%d')
            report_filename = f"market_review_{date_str}.md"
            filepath = notifier.save_report_to_file(
                f"# 🎯 台股覆盤\n\n{review_report}",
                report_filename
            )
            logger.info(f"台股覆盤報告已保存: {filepath}")
            
            # 推送通知
            if send_notification and notifier.is_available():
                # 添加標題
                report_content = f"🎯 台股覆盤\n\n{review_report}"

                success = notifier.send(report_content)
                if success:
                    logger.info("台股覆盤推送成功")
                else:
                    logger.warning("台股覆盤推送失敗")
            elif not send_notification:
                logger.info("已跳過推送通知 (--no-notify)")
            
            return review_report
        
    except Exception as e:
        logger.error(f"台股覆盤分析失敗: {e}")
    
    return None
