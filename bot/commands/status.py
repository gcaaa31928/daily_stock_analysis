# -*- coding: utf-8 -*-
"""
===================================
狀態命令
===================================

顯示系統運行狀態和配置信息。
"""

import platform
import sys
from datetime import datetime
from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse


class StatusCommand(BotCommand):
    """
    狀態命令
    
    顯示系統運行狀態，包括：
    - 服務狀態
    - 配置信息
    - 可用功能
    """
    
    @property
    def name(self) -> str:
        return "status"
    
    @property
    def aliases(self) -> List[str]:
        return ["s", "狀態", "info"]
    
    @property
    def description(self) -> str:
        return "顯示系統狀態"
    
    @property
    def usage(self) -> str:
        return "/status"
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """執行狀態命令"""
        from src.config import get_config
        
        config = get_config()
        
        # 收集狀態信息
        status_info = self._collect_status(config)
        
        # 格式化輸出
        text = self._format_status(status_info, message.platform)
        
        return BotResponse.markdown_response(text)
    
    def _collect_status(self, config) -> dict:
        """收集系統狀態信息"""
        status = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.system(),
            "stock_count": len(config.stock_list),
            "stock_list": config.stock_list[:5],  # 只顯示前5個
        }
        
        # AI 配置狀態
        status["ai_gemini"] = bool(config.gemini_api_key)
        status["ai_openai"] = bool(config.openai_api_key)
        
        # 搜索服務狀態
        status["search_bocha"] = len(config.bocha_api_keys) > 0
        status["search_tavily"] = len(config.tavily_api_keys) > 0
        status["search_serpapi"] = len(config.serpapi_keys) > 0
        
        # 通知渠道狀態
        status["notify_wechat"] = bool(config.wechat_webhook_url)
        status["notify_feishu"] = bool(config.feishu_webhook_url)
        status["notify_telegram"] = bool(config.telegram_bot_token and config.telegram_chat_id)
        status["notify_email"] = bool(config.email_sender and config.email_password)
        
        return status
    
    def _format_status(self, status: dict, platform: str) -> str:
        """格式化狀態信息"""
        # 狀態圖標
        def icon(enabled: bool) -> str:
            return "✅" if enabled else "❌"
        
        lines = [
            "📊 **股票分析助手 - 系統狀態**",
            "",
            f"🕐 時間: {status['timestamp']}",
            f"🐍 Python: {status['python_version']}",
            f"💻 平臺: {status['platform']}",
            "",
            "---",
            "",
            "**📈 自選股配置**",
            f"• 股票數量: {status['stock_count']} 只",
        ]
        
        if status['stock_list']:
            stocks_preview = ", ".join(status['stock_list'])
            if status['stock_count'] > 5:
                stocks_preview += f" ... 等 {status['stock_count']} 只"
            lines.append(f"• 股票列表: {stocks_preview}")
        
        lines.extend([
            "",
            "**🤖 AI 分析服務**",
            f"• Gemini API: {icon(status['ai_gemini'])}",
            f"• OpenAI API: {icon(status['ai_openai'])}",
            "",
            "**🔍 搜索服務**",
            f"• Bocha: {icon(status['search_bocha'])}",
            f"• Tavily: {icon(status['search_tavily'])}",
            f"• SerpAPI: {icon(status['search_serpapi'])}",
            "",
            "**📢 通知渠道**",
            f"• 企業微信: {icon(status['notify_wechat'])}",
            f"• 飛書: {icon(status['notify_feishu'])}",
            f"• Telegram: {icon(status['notify_telegram'])}",
            f"• 郵件: {icon(status['notify_email'])}",
        ])
        
        # AI 服務總體狀態
        ai_available = status['ai_gemini'] or status['ai_openai']
        if ai_available:
            lines.extend([
                "",
                "---",
                "✅ **系統就緒，可以開始分析！**",
            ])
        else:
            lines.extend([
                "",
                "---",
                "⚠️ **AI 服務未配置，分析功能不可用**",
                "請配置 Gemini 或 OpenAI API Key",
            ])
        
        return "\n".join(lines)
