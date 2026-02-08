# -*- coding: utf-8 -*-
"""
===================================
股票分析命令
===================================

分析指定股票，調用 AI 生成分析報告。
"""

import re
import logging
from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class AnalyzeCommand(BotCommand):
    """
    股票分析命令
    
    分析指定股票代碼，生成 AI 分析報告並推送。
    
    用法：
        /analyze 600519       - 分析貴州茅臺（精簡報告）
        /analyze 600519 full  - 分析並生成完整報告
    """
    
    @property
    def name(self) -> str:
        return "analyze"
    
    @property
    def aliases(self) -> List[str]:
        return ["a", "分析", "查"]
    
    @property
    def description(self) -> str:
        return "分析指定股票"
    
    @property
    def usage(self) -> str:
        return "/analyze <股票代碼> [full]"
    
    def validate_args(self, args: List[str]) -> Optional[str]:
        """驗證參數"""
        if not args:
            return "請輸入股票代碼"
        
        code = args[0].upper()

        # 驗證股票代碼格式
        # 台股：4位數字+.TW 或 .TWO（如 2330.TW）
        # A股：6位數字，可帶 .SS/.SZ 後綴（如 600519、600519.SS）
        # 港股：4-5位數字+.HK 或 HK+5位數字（如 0700.HK、HK00700）
        # 美股：1-5個大寫字母（如 AAPL、TSLA）
        is_tw_stock = re.match(r'^\d{4}\.TW(O)?$', code)
        is_a_stock = re.match(r'^\d{6}(\.(SS|SZ))?$', code)
        is_hk_stock = re.match(r'^(HK\d{5}|\d{4,5}\.HK)$', code)
        is_us_stock = re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', code)

        if not (is_tw_stock or is_a_stock or is_hk_stock or is_us_stock):
            return f"無效的股票代碼: {code}（台股4位數字.TW / A股6位數字 / 港股4-5位數字.HK / 美股1-5個字母）"
        
        return None
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """執行分析命令"""
        code = args[0].lower()
        
        # 檢查是否需要完整報告（預設精簡，傳 full/完整/詳細 切換）
        report_type = "simple"
        if len(args) > 1 and args[1].lower() in ["full", "完整", "詳細"]:
            report_type = "full"
        logger.info(f"[AnalyzeCommand] 分析股票: {code}, 報告類型: {report_type}")

        try:
            # 調用分析服務
            from src.services.task_service import get_task_service
            from src.enums import ReportType
            
            service = get_task_service()
            
            # 提交異步分析任務
            result = service.submit_analysis(
                code=code,
                report_type=ReportType.from_str(report_type),
                source_message=message
            )
            
            if result.get("success"):
                task_id = result.get("task_id", "")
                return BotResponse.markdown_response(
                    f"✅ **分析任務已提交**\n\n"
                    f"• 股票代碼: `{code}`\n"
                    f"• 報告類型: {ReportType.from_str(report_type).display_name}\n"
                    f"• 任務 ID: `{task_id[:20]}...`\n\n"
                    f"分析完成後將自動推送結果。"
                )
            else:
                error = result.get("error", "未知錯誤")
                return BotResponse.error_response(f"提交分析任務失敗: {error}")
                
        except Exception as e:
            logger.error(f"[AnalyzeCommand] 執行失敗: {e}")
            return BotResponse.error_response(f"分析失敗: {str(e)[:100]}")
