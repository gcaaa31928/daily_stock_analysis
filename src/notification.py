# -*- coding: utf-8 -*-
"""
===================================
A股自選股智能分析系統 - 通知層
===================================

職責：
1. 彙總分析結果生成日報
2. 支持 Markdown 格式輸出
3. 多渠道推送（自動識別）：
   - 企業微信 Webhook
   - 飛書 Webhook
   - Telegram Bot
   - 郵件 SMTP
   - Pushover（手機/桌面推送）
"""
import hashlib
import hmac
import logging
import json
import smtplib
import re
import markdown2
from datetime import datetime
from typing import List, Dict, Any, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from enum import Enum

import requests
try:
    import discord
    discord_available = True
except ImportError:
    discord_available = False

from src.config import get_config
from src.analyzer import AnalysisResult
from src.formatters import format_feishu_markdown
from bot.models import BotMessage

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """通知渠道類型"""
    WECHAT = "wechat"      # 企業微信
    FEISHU = "feishu"      # 飛書
    TELEGRAM = "telegram"  # Telegram
    EMAIL = "email"        # 郵件
    PUSHOVER = "pushover"  # Pushover（手機/桌面推送）
    PUSHPLUS = "pushplus"  # PushPlus（國內推送服務）
    SERVERCHAN3 = "serverchan3"  # Server醬3（手機APP推送服務）
    CUSTOM = "custom"      # 自定義 Webhook
    DISCORD = "discord"    # Discord 機器人 (Bot)
    ASTRBOT = "astrbot"
    UNKNOWN = "unknown"    # 未知


# SMTP 服務器配置（自動識別）
SMTP_CONFIGS = {
    # QQ郵箱
    "qq.com": {"server": "smtp.qq.com", "port": 465, "ssl": True},
    "foxmail.com": {"server": "smtp.qq.com", "port": 465, "ssl": True},
    # 網易郵箱
    "163.com": {"server": "smtp.163.com", "port": 465, "ssl": True},
    "126.com": {"server": "smtp.126.com", "port": 465, "ssl": True},
    # Gmail
    "gmail.com": {"server": "smtp.gmail.com", "port": 587, "ssl": False},
    # Outlook
    "outlook.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    "hotmail.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    "live.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    # 新浪
    "sina.com": {"server": "smtp.sina.com", "port": 465, "ssl": True},
    # 搜狐
    "sohu.com": {"server": "smtp.sohu.com", "port": 465, "ssl": True},
    # 阿里雲
    "aliyun.com": {"server": "smtp.aliyun.com", "port": 465, "ssl": True},
    # 139郵箱
    "139.com": {"server": "smtp.139.com", "port": 465, "ssl": True},
}


class ChannelDetector:
    """
    渠道檢測器 - 簡化版
    
    根據配置直接判斷渠道類型（不再需要 URL 解析）
    """
    
    @staticmethod
    def get_channel_name(channel: NotificationChannel) -> str:
        """獲取渠道中文名稱"""
        names = {
            NotificationChannel.WECHAT: "企業微信",
            NotificationChannel.FEISHU: "飛書",
            NotificationChannel.TELEGRAM: "Telegram",
            NotificationChannel.EMAIL: "郵件",
            NotificationChannel.PUSHOVER: "Pushover",
            NotificationChannel.PUSHPLUS: "PushPlus",
            NotificationChannel.SERVERCHAN3: "Server醬3",
            NotificationChannel.CUSTOM: "自定義Webhook",
            NotificationChannel.DISCORD: "Discord機器人",
            NotificationChannel.ASTRBOT: "ASTRBOT機器人",
            NotificationChannel.UNKNOWN: "未知渠道",
        }
        return names.get(channel, "未知渠道")


class NotificationService:
    """
    通知服務
    
    職責：
    1. 生成 Markdown 格式的分析日報
    2. 向所有已配置的渠道推送消息（多渠道併發）
    3. 支持本地保存日報
    
    支持的渠道：
    - 企業微信 Webhook
    - 飛書 Webhook
    - Telegram Bot
    - 郵件 SMTP
    - Pushover（手機/桌面推送）
    
    注意：所有已配置的渠道都會收到推送
    """
    
    def __init__(self, source_message: Optional[BotMessage] = None):
        """
        初始化通知服務
        
        檢測所有已配置的渠道，推送時會向所有渠道發送
        """
        config = get_config()
        self._source_message = source_message
        self._context_channels: List[str] = []
        
        # 各渠道的 Webhook URL
        self._wechat_url = config.wechat_webhook_url
        self._feishu_url = getattr(config, 'feishu_webhook_url', None)

        # 微信消息類型配置
        self._wechat_msg_type = getattr(config, 'wechat_msg_type', 'markdown')
        # Telegram 配置
        self._telegram_config = {
            'bot_token': getattr(config, 'telegram_bot_token', None),
            'chat_id': getattr(config, 'telegram_chat_id', None),
            'message_thread_id': getattr(config, 'telegram_message_thread_id', None),
        }
        
        # 郵件配置
        self._email_config = {
            'sender': config.email_sender,
            'sender_name': getattr(config, 'email_sender_name', 'daily_stock_analysis股票分析助手'),
            'password': config.email_password,
            'receivers': config.email_receivers or ([config.email_sender] if config.email_sender else []),
        }
        
        # Pushover 配置
        self._pushover_config = {
            'user_key': getattr(config, 'pushover_user_key', None),
            'api_token': getattr(config, 'pushover_api_token', None),
        }

        # PushPlus 配置
        self._pushplus_token = getattr(config, 'pushplus_token', None)

        # Server醬3 配置
        self._serverchan3_sendkey = getattr(config, 'serverchan3_sendkey', None)

        # 自定義 Webhook 配置
        self._custom_webhook_urls = getattr(config, 'custom_webhook_urls', []) or []
        self._custom_webhook_bearer_token = getattr(config, 'custom_webhook_bearer_token', None)
        
        # Discord 配置
        self._discord_config = {
            'bot_token': getattr(config, 'discord_bot_token', None),
            'channel_id': getattr(config, 'discord_main_channel_id', None),
            'webhook_url': getattr(config, 'discord_webhook_url', None),
        }

        self._astrbot_config = {
            'astrbot_url': getattr(config, 'astrbot_url', None),
            'astrbot_token': getattr(config, 'astrbot_token', None),
        }
        
        # 消息長度限制（字節）
        self._feishu_max_bytes = getattr(config, 'feishu_max_bytes', 20000)
        self._wechat_max_bytes = getattr(config, 'wechat_max_bytes', 4000)
        
        # 檢測所有已配置的渠道
        self._available_channels = self._detect_all_channels()
        if self._has_context_channel():
            self._context_channels.append("釘釘會話")
        
        if not self._available_channels and not self._context_channels:
            logger.warning("未配置有效的通知渠道，將不發送推送通知")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            channel_names.extend(self._context_channels)
            logger.info(f"已配置 {len(channel_names)} 個通知渠道：{', '.join(channel_names)}")
    
    def _detect_all_channels(self) -> List[NotificationChannel]:
        """
        檢測所有已配置的渠道
        
        Returns:
            已配置的渠道列表
        """
        channels = []
        
        # 企業微信
        if self._wechat_url:
            channels.append(NotificationChannel.WECHAT)
        
        # 飛書
        if self._feishu_url:
            channels.append(NotificationChannel.FEISHU)
        
        # Telegram
        if self._is_telegram_configured():
            channels.append(NotificationChannel.TELEGRAM)
        
        # 郵件
        if self._is_email_configured():
            channels.append(NotificationChannel.EMAIL)
        
        # Pushover
        if self._is_pushover_configured():
            channels.append(NotificationChannel.PUSHOVER)

        # PushPlus
        if self._pushplus_token:
            channels.append(NotificationChannel.PUSHPLUS)

        # Server醬3
        if self._serverchan3_sendkey:
            channels.append(NotificationChannel.SERVERCHAN3)

        # 自定義 Webhook
        if self._custom_webhook_urls:
            channels.append(NotificationChannel.CUSTOM)
        
        # Discord
        if self._is_discord_configured():
            channels.append(NotificationChannel.DISCORD)
        # AstrBot
        if self._is_astrbot_configured():
            channels.append(NotificationChannel.ASTRBOT)
        return channels
    
    def _is_telegram_configured(self) -> bool:
        """檢查 Telegram 配置是否完整"""
        return bool(self._telegram_config['bot_token'] and self._telegram_config['chat_id'])
    
    def _is_discord_configured(self) -> bool:
        """檢查 Discord 配置是否完整（支持 Bot 或 Webhook）"""
        # 只要配置了 Webhook 或完整的 Bot Token+Channel，即視為可用
        bot_ok = bool(self._discord_config['bot_token'] and self._discord_config['channel_id'])
        webhook_ok = bool(self._discord_config['webhook_url'])
        return bot_ok or webhook_ok

    def _is_astrbot_configured(self) -> bool:
        """檢查 AstrBot 配置是否完整（支持 Bot 或 Webhook）"""
        # 只要配置了 URL，即視為可用
        url_ok = bool(self._astrbot_config['astrbot_url'])
        return url_ok

    def _is_email_configured(self) -> bool:
        """檢查郵件配置是否完整（只需郵箱和授權碼）"""
        return bool(self._email_config['sender'] and self._email_config['password'])
    
    def _is_pushover_configured(self) -> bool:
        """檢查 Pushover 配置是否完整"""
        return bool(self._pushover_config['user_key'] and self._pushover_config['api_token'])
    
    def is_available(self) -> bool:
        """檢查通知服務是否可用（至少有一個渠道或上下文渠道）"""
        return len(self._available_channels) > 0 or self._has_context_channel()
    
    def get_available_channels(self) -> List[NotificationChannel]:
        """獲取所有已配置的渠道"""
        return self._available_channels
    
    def get_channel_names(self) -> str:
        """獲取所有已配置渠道的名稱"""
        names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
        if self._has_context_channel():
            names.append("釘釘會話")
        return ', '.join(names)

    def _has_context_channel(self) -> bool:
        """判斷是否存在基於消息上下文的臨時渠道（如釘釘會話、飛書會話）"""
        return (
            self._extract_dingtalk_session_webhook() is not None
            or self._extract_feishu_reply_info() is not None
        )

    def _extract_dingtalk_session_webhook(self) -> Optional[str]:
        """從來源消息中提取釘釘會話 Webhook（用於 Stream 模式回覆）"""
        if not isinstance(self._source_message, BotMessage):
            return None
        raw_data = getattr(self._source_message, "raw_data", {}) or {}
        if not isinstance(raw_data, dict):
            return None
        session_webhook = (
            raw_data.get("_session_webhook")
            or raw_data.get("sessionWebhook")
            or raw_data.get("session_webhook")
            or raw_data.get("session_webhook_url")
        )
        if not session_webhook and isinstance(raw_data.get("headers"), dict):
            session_webhook = raw_data["headers"].get("sessionWebhook")
        return session_webhook

    def _extract_feishu_reply_info(self) -> Optional[Dict[str, str]]:
        """
        從來源消息中提取飛書回覆信息（用於 Stream 模式回覆）
        
        Returns:
            包含 chat_id 的字典，或 None
        """
        if not isinstance(self._source_message, BotMessage):
            return None
        if getattr(self._source_message, "platform", "") != "feishu":
            return None
        chat_id = getattr(self._source_message, "chat_id", "")
        if not chat_id:
            return None
        return {"chat_id": chat_id}

    def send_to_context(self, content: str) -> bool:
        """
        向基於消息上下文的渠道發送消息（例如釘釘 Stream 會話）
        
        Args:
            content: Markdown 格式內容
        """
        return self._send_via_source_context(content)
    
    def generate_daily_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        生成 Markdown 格式的日報（詳細版）

        Args:
            results: 分析結果列表
            report_date: 報告日期（默認今天）


        Returns:
            Markdown 格式的日報內容
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        # 標題
        report_lines = [
            f"# 📅 {report_date} 股票智能分析報告",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 報告生成時間：{datetime.now().strftime('%H:%M:%S')}",
            "",
            "---",
            "",
        ]
        
        # 按評分排序（高分在前）
        sorted_results = sorted(
            results, 
            key=lambda x: x.sentiment_score, 
            reverse=True
        )
        
        # 統計信息 - 使用 decision_type 欄位準確統計
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0
        
        report_lines.extend([
            "## 📊 操作建議彙總",
            "",
            "| 指標 | 數值 |",
            "|------|------|",
            f"| 🟢 建議買入/加倉 | **{buy_count}** 只 |",
            f"| 🟡 建議持有/觀望 | **{hold_count}** 只 |",
            f"| 🔴 建議減倉/賣出 | **{sell_count}** 只 |",
            f"| 📈 平均看多評分 | **{avg_score:.1f}** 分 |",
            "",
            "---",
            "",
            "## 📈 個股詳細分析",
            "",
        ])
        
        # 逐個股票的詳細分析
        for result in sorted_results:
            emoji = result.get_emoji()
            confidence_stars = result.get_confidence_stars() if hasattr(result, 'get_confidence_stars') else '⭐⭐'
            
            report_lines.extend([
                f"### {emoji} {result.name} ({result.code})",
                "",
                f"**操作建議：{result.operation_advice}** | **綜合評分：{result.sentiment_score}分** | **趨勢預測：{result.trend_prediction}** | **置信度：{confidence_stars}**",
                "",
            ])

            self._append_market_snapshot(report_lines, result)
            
            # 核心看點
            if hasattr(result, 'key_points') and result.key_points:
                report_lines.extend([
                    f"**🎯 核心看點**：{result.key_points}",
                    "",
                ])
            
            # 買入/賣出理由
            if hasattr(result, 'buy_reason') and result.buy_reason:
                report_lines.extend([
                    f"**💡 操作理由**：{result.buy_reason}",
                    "",
                ])
            
            # 走勢分析
            if hasattr(result, 'trend_analysis') and result.trend_analysis:
                report_lines.extend([
                    "#### 📉 走勢分析",
                    f"{result.trend_analysis}",
                    "",
                ])
            
            # 短期/中期展望
            outlook_lines = []
            if hasattr(result, 'short_term_outlook') and result.short_term_outlook:
                outlook_lines.append(f"- **短期（1-3日）**：{result.short_term_outlook}")
            if hasattr(result, 'medium_term_outlook') and result.medium_term_outlook:
                outlook_lines.append(f"- **中期（1-2周）**：{result.medium_term_outlook}")
            if outlook_lines:
                report_lines.extend([
                    "#### 🔮 市場展望",
                    *outlook_lines,
                    "",
                ])
            
            # 技術面分析
            tech_lines = []
            if result.technical_analysis:
                tech_lines.append(f"**綜合**：{result.technical_analysis}")
            if hasattr(result, 'ma_analysis') and result.ma_analysis:
                tech_lines.append(f"**均線**：{result.ma_analysis}")
            if hasattr(result, 'volume_analysis') and result.volume_analysis:
                tech_lines.append(f"**量能**：{result.volume_analysis}")
            if hasattr(result, 'pattern_analysis') and result.pattern_analysis:
                tech_lines.append(f"**形態**：{result.pattern_analysis}")
            if tech_lines:
                report_lines.extend([
                    "#### 📊 技術面分析",
                    *tech_lines,
                    "",
                ])
            
            # 基本面分析
            fund_lines = []
            if hasattr(result, 'fundamental_analysis') and result.fundamental_analysis:
                fund_lines.append(result.fundamental_analysis)
            if hasattr(result, 'sector_position') and result.sector_position:
                fund_lines.append(f"**板塊地位**：{result.sector_position}")
            if hasattr(result, 'company_highlights') and result.company_highlights:
                fund_lines.append(f"**公司亮點**：{result.company_highlights}")
            if fund_lines:
                report_lines.extend([
                    "#### 🏢 基本面分析",
                    *fund_lines,
                    "",
                ])
            
            # 消息面/情緒面
            news_lines = []
            if result.news_summary:
                news_lines.append(f"**新聞摘要**：{result.news_summary}")
            if hasattr(result, 'market_sentiment') and result.market_sentiment:
                news_lines.append(f"**市場情緒**：{result.market_sentiment}")
            if hasattr(result, 'hot_topics') and result.hot_topics:
                news_lines.append(f"**相關熱點**：{result.hot_topics}")
            if news_lines:
                report_lines.extend([
                    "#### 📰 消息面/情緒面",
                    *news_lines,
                    "",
                ])
            
            # 綜合分析
            if result.analysis_summary:
                report_lines.extend([
                    "#### 📝 綜合分析",
                    result.analysis_summary,
                    "",
                ])
            
            # 風險提示
            if hasattr(result, 'risk_warning') and result.risk_warning:
                report_lines.extend([
                    f"⚠️ **風險提示**：{result.risk_warning}",
                    "",
                ])
            
            # 數據來源說明
            if hasattr(result, 'search_performed') and result.search_performed:
                report_lines.append("*🔍 已執行聯網搜索*")
            if hasattr(result, 'data_sources') and result.data_sources:
                report_lines.append(f"*📋 數據來源：{result.data_sources}*")
            
            # 錯誤信息（如果有）
            if not result.success and result.error_message:
                report_lines.extend([
                    "",
                    f"❌ **分析異常**：{result.error_message[:100]}",
                ])
            
            report_lines.extend([
                "",
                "---",
                "",
            ])
        
        # 底部信息（去除免責聲明）
        report_lines.extend([
            "",
            f"*報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    def _get_signal_level(self, result: AnalysisResult) -> tuple:
        """
        根據操作建議獲取信號等級和顏色
        
        Returns:
            (信號文字, emoji, 顏色標記)
        """
        advice = result.operation_advice
        score = result.sentiment_score
        
        if advice in ['強烈買入'] or score >= 80:
            return ('強烈買入', '💚', '強買')
        elif advice in ['買入', '加倉'] or score >= 65:
            return ('買入', '🟢', '買入')
        elif advice in ['持有'] or 55 <= score < 65:
            return ('持有', '🟡', '持有')
        elif advice in ['觀望'] or 45 <= score < 55:
            return ('觀望', '⚪', '觀望')
        elif advice in ['減倉'] or 35 <= score < 45:
            return ('減倉', '🟠', '減倉')
        elif advice in ['賣出', '強烈賣出'] or score < 35:
            return ('賣出', '🔴', '賣出')
        else:
            return ('觀望', '⚪', '觀望')
    
    def generate_dashboard_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        生成決策儀表盤格式的日報（詳細版）

        格式：市場概覽 + 重要信息 + 核心結論 + 數據透視 + 作戰計劃

        Args:
            results: 分析結果列表
            report_date: 報告日期（默認今天）


        Returns:
            Markdown 格式的決策儀表盤日報
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        # 按評分排序（高分在前）
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        # 統計信息 - 使用 decision_type 欄位準確統計
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))


        report_lines = [
            f"# 🎯 {report_date} 決策儀表盤",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 🟢買入:{buy_count} 🟡觀望:{hold_count} 🔴賣出:{sell_count}",
            "",
        ]

        # === 新增：分析結果摘要 (Issue #112) ===
        if results:
            report_lines.extend([
                "## 📊 分析結果摘要",
                "",
            ])
            for r in sorted_results:
                emoji = r.get_emoji()
                report_lines.append(
                    f"{emoji} **{r.name}({r.code})**: {r.operation_advice} | "
                    f"評分 {r.sentiment_score} | {r.trend_prediction}"
                )
            report_lines.extend([
                "",
                "---",
                "",
            ])

        # 逐個股票的決策儀表盤
        for result in sorted_results:
            signal_text, signal_emoji, signal_tag = self._get_signal_level(result)
            dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
            
            # 股票名稱（優先使用 dashboard 或 result 中的名稱）
            stock_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
            
            report_lines.extend([
                f"## {signal_emoji} {stock_name} ({result.code})",
                "",
            ])
            
            # ========== 輿情與基本面概覽（放在最前面）==========
            intel = dashboard.get('intelligence', {}) if dashboard else {}
            if intel:
                report_lines.extend([
                    "### 📰 重要信息速覽",
                    "",
                ])
                
                # 輿情情緒總結
                if intel.get('sentiment_summary'):
                    report_lines.append(f"**💭 輿情情緒**: {intel['sentiment_summary']}")
                
                # 業績預期
                if intel.get('earnings_outlook'):
                    report_lines.append(f"**📊 業績預期**: {intel['earnings_outlook']}")
                
                # 風險警報（醒目顯示）
                risk_alerts = intel.get('risk_alerts', [])
                if risk_alerts:
                    report_lines.append("")
                    report_lines.append("**🚨 風險警報**:")
                    for alert in risk_alerts:
                        report_lines.append(f"- {alert}")
                
                # 利好催化
                catalysts = intel.get('positive_catalysts', [])
                if catalysts:
                    report_lines.append("")
                    report_lines.append("**✨ 利好催化**:")
                    for cat in catalysts:
                        report_lines.append(f"- {cat}")
                
                # 最新消息
                if intel.get('latest_news'):
                    report_lines.append("")
                    report_lines.append(f"**📢 最新動態**: {intel['latest_news']}")
                
                report_lines.append("")
            
            # ========== 核心結論 ==========
            core = dashboard.get('core_conclusion', {}) if dashboard else {}
            one_sentence = core.get('one_sentence', result.analysis_summary)
            time_sense = core.get('time_sensitivity', '本週內')
            pos_advice = core.get('position_advice', {})
            
            report_lines.extend([
                "### 📌 核心結論",
                "",
                f"**{signal_emoji} {signal_text}** | {result.trend_prediction}",
                "",
                f"> **一句話決策**: {one_sentence}",
                "",
                f"⏰ **時效性**: {time_sense}",
                "",
            ])
            
            # 持倉分類建議
            if pos_advice:
                report_lines.extend([
                    "| 持倉情況 | 操作建議 |",
                    "|---------|---------|",
                    f"| 🆕 **空倉者** | {pos_advice.get('no_position', result.operation_advice)} |",
                    f"| 💼 **持倉者** | {pos_advice.get('has_position', '繼續持有')} |",
                    "",
                ])

            self._append_market_snapshot(report_lines, result)
            
            # ========== 數據透視 ==========
            data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
            if data_persp:
                trend_data = data_persp.get('trend_status', {})
                price_data = data_persp.get('price_position', {})
                vol_data = data_persp.get('volume_analysis', {})
                chip_data = data_persp.get('chip_structure', {})
                
                report_lines.extend([
                    "### 📊 數據透視",
                    "",
                ])
                
                # 趨勢狀態
                if trend_data:
                    is_bullish = "✅ 是" if trend_data.get('is_bullish', False) else "❌ 否"
                    report_lines.extend([
                        f"**均線排列**: {trend_data.get('ma_alignment', 'N/A')} | 多頭排列: {is_bullish} | 趨勢強度: {trend_data.get('trend_score', 'N/A')}/100",
                        "",
                    ])
                
                # 價格位置
                if price_data:
                    bias_status = price_data.get('bias_status', 'N/A')
                    bias_emoji = "✅" if bias_status == "安全" else ("⚠️" if bias_status == "警戒" else "🚨")
                    report_lines.extend([
                        "| 價格指標 | 數值 |",
                        "|---------|------|",
                        f"| 當前價 | {price_data.get('current_price', 'N/A')} |",
                        f"| MA5 | {price_data.get('ma5', 'N/A')} |",
                        f"| MA10 | {price_data.get('ma10', 'N/A')} |",
                        f"| MA20 | {price_data.get('ma20', 'N/A')} |",
                        f"| 乖離率(MA5) | {price_data.get('bias_ma5', 'N/A')}% {bias_emoji}{bias_status} |",
                        f"| 支撐位 | {price_data.get('support_level', 'N/A')} |",
                        f"| 壓力位 | {price_data.get('resistance_level', 'N/A')} |",
                        "",
                    ])
                
                # 量能分析
                if vol_data:
                    report_lines.extend([
                        f"**量能**: 量比 {vol_data.get('volume_ratio', 'N/A')} ({vol_data.get('volume_status', '')}) | 換手率 {vol_data.get('turnover_rate', 'N/A')}%",
                        f"💡 *{vol_data.get('volume_meaning', '')}*",
                        "",
                    ])
                
                # 籌碼結構
                if chip_data:
                    chip_health = chip_data.get('chip_health', 'N/A')
                    chip_emoji = "✅" if chip_health == "健康" else ("⚠️" if chip_health == "一般" else "🚨")
                    report_lines.extend([
                        f"**籌碼**: 獲利比例 {chip_data.get('profit_ratio', 'N/A')} | 平均成本 {chip_data.get('avg_cost', 'N/A')} | 集中度 {chip_data.get('concentration', 'N/A')} {chip_emoji}{chip_health}",
                        "",
                    ])
            
            # 輿情情報已移至頂部顯示
            
            # ========== 作戰計劃 ==========
            battle = dashboard.get('battle_plan', {}) if dashboard else {}
            if battle:
                report_lines.extend([
                    "### 🎯 作戰計劃",
                    "",
                ])
                
                # 狙擊點位
                sniper = battle.get('sniper_points', {})
                if sniper:
                    report_lines.extend([
                        "**📍 狙擊點位**",
                        "",
                        "| 點位類型 | 價格 |",
                        "|---------|------|",
                        f"| 🎯 理想買入點 | {sniper.get('ideal_buy', 'N/A')} |",
                        f"| 🔵 次優買入點 | {sniper.get('secondary_buy', 'N/A')} |",
                        f"| 🛑 止損位 | {sniper.get('stop_loss', 'N/A')} |",
                        f"| 🎊 目標位 | {sniper.get('take_profit', 'N/A')} |",
                        "",
                    ])
                
                # 倉位策略
                position = battle.get('position_strategy', {})
                if position:
                    report_lines.extend([
                        f"**💰 倉位建議**: {position.get('suggested_position', 'N/A')}",
                        f"- 建倉策略: {position.get('entry_plan', 'N/A')}",
                        f"- 風控策略: {position.get('risk_control', 'N/A')}",
                        "",
                    ])
                
                # 檢查清單
                checklist = battle.get('action_checklist', []) if battle else []
                if checklist:
                    report_lines.extend([
                        "**✅ 檢查清單**",
                        "",
                    ])
                    for item in checklist:
                        report_lines.append(f"- {item}")
                    report_lines.append("")
            
            # 如果沒有 dashboard，顯示傳統格式
            if not dashboard:
                # 操作理由
                if result.buy_reason:
                    report_lines.extend([
                        f"**💡 操作理由**: {result.buy_reason}",
                        "",
                    ])
                
                # 風險提示
                if result.risk_warning:
                    report_lines.extend([
                        f"**⚠️ 風險提示**: {result.risk_warning}",
                        "",
                    ])
                
                # 技術面分析
                if result.ma_analysis or result.volume_analysis:
                    report_lines.extend([
                        "### 📊 技術面",
                        "",
                    ])
                    if result.ma_analysis:
                        report_lines.append(f"**均線**: {result.ma_analysis}")
                    if result.volume_analysis:
                        report_lines.append(f"**量能**: {result.volume_analysis}")
                    report_lines.append("")
                
                # 消息面
                if result.news_summary:
                    report_lines.extend([
                        "### 📰 消息面",
                        f"{result.news_summary}",
                        "",
                    ])
            
            report_lines.extend([
                "---",
                "",
            ])
        
        # 底部（去除免責聲明）
        report_lines.extend([
            "",
            f"*報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    def generate_wechat_dashboard(self, results: List[AnalysisResult]) -> str:
        """
        生成企業微信決策儀表盤精簡版（控制在4000字符內）
        
        只保留核心結論和狙擊點位
        
        Args:
            results: 分析結果列表
            
        Returns:
            精簡版決策儀表盤
        """
        report_date = datetime.now().strftime('%Y-%m-%d')
        
        # 按評分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        
        # 統計 - 使用 decision_type 欄位準確統計
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))

        lines = [
            f"## 🎯 {report_date} 決策儀表盤",
            "",
            f"> {len(results)}只股票 | 🟢買入:{buy_count} 🟡觀望:{hold_count} 🔴賣出:{sell_count}",
            "",
        ]
        
        for result in sorted_results:
            signal_text, signal_emoji, _ = self._get_signal_level(result)
            dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
            core = dashboard.get('core_conclusion', {}) if dashboard else {}
            battle = dashboard.get('battle_plan', {}) if dashboard else {}
            intel = dashboard.get('intelligence', {}) if dashboard else {}
            
            # 股票名稱
            stock_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
            
            # 標題行：信號等級 + 股票名稱
            lines.append(f"### {signal_emoji} **{signal_text}** | {stock_name}({result.code})")
            lines.append("")
            
            # 核心決策（一句話）
            one_sentence = core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
            if one_sentence:
                lines.append(f"📌 **{one_sentence[:80]}**")
                lines.append("")
            
            # 重要信息區（輿情+基本面）
            info_lines = []
            
            # 業績預期
            if intel.get('earnings_outlook'):
                outlook = intel['earnings_outlook'][:60]
                info_lines.append(f"📊 業績: {outlook}")
            
            # 輿情情緒
            if intel.get('sentiment_summary'):
                sentiment = intel['sentiment_summary'][:50]
                info_lines.append(f"💭 輿情: {sentiment}")
            
            if info_lines:
                lines.extend(info_lines)
                lines.append("")
            
            # 風險警報（最重要，醒目顯示）
            risks = intel.get('risk_alerts', []) if intel else []
            if risks:
                lines.append("🚨 **風險**:")
                for risk in risks[:2]:  # 最多顯示2條
                    risk_text = risk[:50] + "..." if len(risk) > 50 else risk
                    lines.append(f"   • {risk_text}")
                lines.append("")
            
            # 利好催化
            catalysts = intel.get('positive_catalysts', []) if intel else []
            if catalysts:
                lines.append("✨ **利好**:")
                for cat in catalysts[:2]:  # 最多顯示2條
                    cat_text = cat[:50] + "..." if len(cat) > 50 else cat
                    lines.append(f"   • {cat_text}")
                lines.append("")
            
            # 狙擊點位
            sniper = battle.get('sniper_points', {}) if battle else {}
            if sniper:
                ideal_buy = sniper.get('ideal_buy', '')
                stop_loss = sniper.get('stop_loss', '')
                take_profit = sniper.get('take_profit', '')
                
                points = []
                if ideal_buy:
                    points.append(f"🎯買點:{ideal_buy[:15]}")
                if stop_loss:
                    points.append(f"🛑止損:{stop_loss[:15]}")
                if take_profit:
                    points.append(f"🎊目標:{take_profit[:15]}")
                
                if points:
                    lines.append(" | ".join(points))
                    lines.append("")
            
            # 持倉建議
            pos_advice = core.get('position_advice', {}) if core else {}
            if pos_advice:
                no_pos = pos_advice.get('no_position', '')
                has_pos = pos_advice.get('has_position', '')
                if no_pos:
                    lines.append(f"🆕 空倉者: {no_pos[:50]}")
                if has_pos:
                    lines.append(f"💼 持倉者: {has_pos[:50]}")
                lines.append("")
            
            # 檢查清單簡化版
            checklist = battle.get('action_checklist', []) if battle else []
            if checklist:
                # 只顯示不通過的項目
                failed_checks = [c for c in checklist if c.startswith('❌') or c.startswith('⚠️')]
                if failed_checks:
                    lines.append("**檢查未通過項**:")
                    for check in failed_checks[:3]:
                        lines.append(f"   {check[:40]}")
                    lines.append("")
            
            lines.append("---")
            lines.append("")
        
        # 底部
        lines.append(f"*生成時間: {datetime.now().strftime('%H:%M')}*")
        
        content = "\n".join(lines)
        
        return content
    
    def generate_wechat_summary(self, results: List[AnalysisResult]) -> str:
        """
        生成企業微信精簡版日報（控制在4000字符內）

        Args:
            results: 分析結果列表


        Returns:
            精簡版 Markdown 內容
        """
        report_date = datetime.now().strftime('%Y-%m-%d')

        # 按評分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        # 統計 - 使用 decision_type 欄位準確統計
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0

        lines = [
            f"## 📅 {report_date} 股票分析報告",
            "",
            f"> 共 **{len(results)}** 只 | 🟢買入:{buy_count} 🟡持有:{hold_count} 🔴賣出:{sell_count} | 均分:{avg_score:.0f}",
            "",
        ]
        
        # 每隻股票精簡信息（控制長度）
        for result in sorted_results:
            emoji = result.get_emoji()
            
            # 核心信息行
            lines.append(f"### {emoji} {result.name}({result.code})")
            lines.append(f"**{result.operation_advice}** | 評分:{result.sentiment_score} | {result.trend_prediction}")
            
            # 操作理由（截斷）
            if hasattr(result, 'buy_reason') and result.buy_reason:
                reason = result.buy_reason[:80] + "..." if len(result.buy_reason) > 80 else result.buy_reason
                lines.append(f"💡 {reason}")
            
            # 核心看點
            if hasattr(result, 'key_points') and result.key_points:
                points = result.key_points[:60] + "..." if len(result.key_points) > 60 else result.key_points
                lines.append(f"🎯 {points}")
            
            # 風險提示（截斷）
            if hasattr(result, 'risk_warning') and result.risk_warning:
                risk = result.risk_warning[:50] + "..." if len(result.risk_warning) > 50 else result.risk_warning
                lines.append(f"⚠️ {risk}")
            
            lines.append("")
        
        # 底部
        lines.extend([
            "---",
            "*AI生成，僅供參考，不構成投資建議*",
            f"*詳細報告見 reports/report_{report_date.replace('-', '')}.md*"
        ])
        
        content = "\n".join(lines)
        
        return content
    
    def generate_single_stock_report(self, result: AnalysisResult) -> str:
        """
        生成單隻股票的分析報告（用於單股推送模式 #55）
        
        格式精簡但信息完整，適合每分析完一隻股票立即推送
        
        Args:
            result: 單隻股票的分析結果
            
        Returns:
            Markdown 格式的單股報告
        """
        report_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        signal_text, signal_emoji, _ = self._get_signal_level(result)
        dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
        core = dashboard.get('core_conclusion', {}) if dashboard else {}
        battle = dashboard.get('battle_plan', {}) if dashboard else {}
        intel = dashboard.get('intelligence', {}) if dashboard else {}
        
        # 股票名稱
        stock_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
        
        lines = [
            f"## {signal_emoji} {stock_name} ({result.code})",
            "",
            f"> {report_date} | 評分: **{result.sentiment_score}** | {result.trend_prediction}",
            "",
        ]

        self._append_market_snapshot(lines, result)
        
        # 核心決策（一句話）
        one_sentence = core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
        if one_sentence:
            lines.extend([
                "### 📌 核心結論",
                "",
                f"**{signal_text}**: {one_sentence}",
                "",
            ])
        
        # 重要信息（輿情+基本面）
        info_added = False
        if intel:
            if intel.get('earnings_outlook'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append(f"📊 **業績預期**: {intel['earnings_outlook'][:100]}")
            
            if intel.get('sentiment_summary'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append(f"💭 **輿情情緒**: {intel['sentiment_summary'][:80]}")
            
            # 風險警報
            risks = intel.get('risk_alerts', [])
            if risks:
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append("")
                lines.append("🚨 **風險警報**:")
                for risk in risks[:3]:
                    lines.append(f"- {risk[:60]}")
            
            # 利好催化
            catalysts = intel.get('positive_catalysts', [])
            if catalysts:
                lines.append("")
                lines.append("✨ **利好催化**:")
                for cat in catalysts[:3]:
                    lines.append(f"- {cat[:60]}")
        
        if info_added:
            lines.append("")
        
        # 狙擊點位
        sniper = battle.get('sniper_points', {}) if battle else {}
        if sniper:
            lines.extend([
                "### 🎯 操作點位",
                "",
                "| 買點 | 止損 | 目標 |",
                "|------|------|------|",
            ])
            ideal_buy = sniper.get('ideal_buy', '-')
            stop_loss = sniper.get('stop_loss', '-')
            take_profit = sniper.get('take_profit', '-')
            lines.append(f"| {ideal_buy} | {stop_loss} | {take_profit} |")
            lines.append("")
        
        # 持倉建議
        pos_advice = core.get('position_advice', {}) if core else {}
        if pos_advice:
            lines.extend([
                "### 💼 持倉建議",
                "",
                f"- 🆕 **空倉者**: {pos_advice.get('no_position', result.operation_advice)}",
                f"- 💼 **持倉者**: {pos_advice.get('has_position', '繼續持有')}",
                "",
            ])
        
        lines.extend([
            "---",
            "*AI生成，僅供參考，不構成投資建議*",
        ])
        
        return "\n".join(lines)

    def _append_market_snapshot(self, lines: List[str], result: AnalysisResult) -> None:
        snapshot = getattr(result, 'market_snapshot', None)
        if not snapshot:
            return

        lines.extend([
            "### 📈 當日行情",
            "",
            "| 收盤 | 昨收 | 開盤 | 最高 | 最低 | 漲跌幅 | 漲跌額 | 振幅 | 成交量 | 成交額 |",
            "|------|------|------|------|------|-------|-------|------|--------|--------|",
            f"| {snapshot.get('close', 'N/A')} | {snapshot.get('prev_close', 'N/A')} | "
            f"{snapshot.get('open', 'N/A')} | {snapshot.get('high', 'N/A')} | "
            f"{snapshot.get('low', 'N/A')} | {snapshot.get('pct_chg', 'N/A')} | "
            f"{snapshot.get('change_amount', 'N/A')} | {snapshot.get('amplitude', 'N/A')} | "
            f"{snapshot.get('volume', 'N/A')} | {snapshot.get('amount', 'N/A')} |",
        ])

        if "price" in snapshot:
            lines.extend([
                "",
                "| 當前價 | 量比 | 換手率 | 行情來源 |",
                "|-------|------|--------|----------|",
                f"| {snapshot.get('price', 'N/A')} | {snapshot.get('volume_ratio', 'N/A')} | "
                f"{snapshot.get('turnover_rate', 'N/A')} | {snapshot.get('source', 'N/A')} |",
            ])

        lines.append("")
    
    def send_to_wechat(self, content: str) -> bool:
        """
        推送消息到企業微信機器人
        
        企業微信 Webhook 消息格式：
        支持 markdown 類型以及 text 類型, markdown 類型在微信中無法展示，可以使用 text 類型,
        markdown 類型會解析 markdown 格式,text 類型會直接發送純文本。

        markdown 類型示例：
        {
            "msgtype": "markdown",
            "markdown": {
                "content": "## 標題\n\n內容"
            }
        }

        text 類型示例：
        {
            "msgtype": "text",
            "text": {
                "content": "內容"
            }
        }

        注意：企業微信 Markdown 限制 4096 字節（非字符）, Text 類型限制 2048 字節，超長內容會自動分批發送
        可通過環境變量 WECHAT_MAX_BYTES 調整限制值
        
        Args:
            content: Markdown 格式的消息內容
            
        Returns:
            是否發送成功
        """
        if not self._wechat_url:
            logger.warning("企業微信 Webhook 未配置，跳過推送")
            return False
        
        # 根據消息類型動態限制上限，避免 text 類型超過企業微信 2048 字節限制
        if self._wechat_msg_type == 'text':
            max_bytes = min(self._wechat_max_bytes, 2000)  # 預留一定字節給系統/分頁標記
        else:
            max_bytes = self._wechat_max_bytes  # markdown 默認 4000 字節
        
        # 檢查字節長度，超長則分批發送
        content_bytes = len(content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"消息內容超長({content_bytes}字節/{len(content)}字符)，將分批發送")
            return self._send_wechat_chunked(content, max_bytes)
        
        try:
            return self._send_wechat_message(content)
        except Exception as e:
            logger.error(f"發送企業微信消息失敗: {e}")
            return False
    
    def _send_wechat_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批發送長消息到企業微信
        
        按股票分析塊（以 --- 或 ### 分隔）智能分割，確保每批不超過限制
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節數
            
        Returns:
            是否全部發送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            """獲取字符串的 UTF-8 字節數"""
            return len(s.encode('utf-8'))
        
        # 智能分割：優先按 "---" 分隔（股票之間的分隔線）
        # 其次嘗試各級標題分割
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            # 按 ### 分割
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        elif "\n## " in content:
            # 按 ## 分割 (兼容二級標題)
            parts = content.split("\n## ")
            sections = [parts[0]] + [f"## {p}" for p in parts[1:]]
            separator = "\n"
        elif "\n**" in content:
            # 按 ** 加粗標題分割 (兼容 AI 未輸出標準 Markdown 標題的情況)
            parts = content.split("\n**")
            sections = [parts[0]] + [f"**{p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 無法智能分割，按字符強制分割
            return self._send_wechat_force_chunked(content, max_bytes)
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        effective_max_bytes = max_bytes - 50  # 預留分頁標記空間，避免邊界超限
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            # 如果單個 section 就超長，需要強制截斷
            if section_bytes > effective_max_bytes:
                # 先發送當前積累的內容
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0
                
                # 強制截斷這個超長 section（按字節截斷）
                truncated = self._truncate_to_bytes(section, effective_max_bytes - 200)
                truncated += "\n\n...(本段內容過長已截斷)"
                chunks.append(truncated)
                continue

            # 檢查加入後是否超長
            if current_bytes + section_bytes > effective_max_bytes:
                # 保存當前塊，開始新塊
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        # 添加最後一塊
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 分批發送
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"企業微信分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分頁標記
            if total_chunks > 1:
                page_marker = f"\n\n📄 *({i+1}/{total_chunks})*"
                chunk_with_marker = chunk + page_marker
            else:
                chunk_with_marker = chunk
            
            try:
                if self._send_wechat_message(chunk_with_marker):
                    success_count += 1
                    logger.info(f"企業微信第 {i+1}/{total_chunks} 批發送成功")
                else:
                    logger.error(f"企業微信第 {i+1}/{total_chunks} 批發送失敗")
            except Exception as e:
                logger.error(f"企業微信第 {i+1}/{total_chunks} 批發送異常: {e}")

            # 批次間隔，避免觸發頻率限制
            if i < total_chunks - 1:
                time.sleep(2.5)  # 增加到 2.5s，避免企業微信限流

        return success_count == total_chunks
    
    def _send_wechat_force_chunked(self, content: str, max_bytes: int) -> bool:
        """
        強制按字節分割發送（無法智能分割時的 fallback）
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節數
        """
        import time
        
        chunks = []
        current_chunk = ""
        
        # 按行分割，確保不會在多字節字符中間截斷
        lines = content.split('\n')
        
        for line in lines:
            test_chunk = current_chunk + ('\n' if current_chunk else '') + line
            if len(test_chunk.encode('utf-8')) > max_bytes - 100:  # 預留空間給分頁標記
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = test_chunk
        
        if current_chunk:
            chunks.append(current_chunk)
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"企業微信強制分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            page_marker = f"\n\n📄 *({i+1}/{total_chunks})*" if total_chunks > 1 else ""
            
            try:
                if self._send_wechat_message(chunk + page_marker):
                    success_count += 1
            except Exception as e:
                logger.error(f"企業微信第 {i+1}/{total_chunks} 批發送異常: {e}")
            
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _truncate_to_bytes(self, text: str, max_bytes: int) -> str:
        """
        按字節數截斷字符串，確保不會在多字節字符中間截斷
        
        Args:
            text: 要截斷的字符串
            max_bytes: 最大字節數
            
        Returns:
            截斷後的字符串
        """
        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text
        
        # 從 max_bytes 位置往前找，確保不截斷多字節字符
        truncated = encoded[:max_bytes]
        # 嘗試解碼，如果失敗則繼續往前
        while truncated:
            try:
                return truncated.decode('utf-8')
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""
    
    def _gen_wechat_payload(self, content: str) -> dict:
        """生成企業微信消息 payload"""
        if self._wechat_msg_type == 'text':
            return {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
        else:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }

    def _send_wechat_message(self, content: str) -> bool:
        """發送企業微信消息"""
        payload = self._gen_wechat_payload(content)
        
        response = requests.post(
            self._wechat_url,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                logger.info("企業微信消息發送成功")
                return True
            else:
                logger.error(f"企業微信返回錯誤: {result}")
                return False
        else:
            logger.error(f"企業微信請求失敗: {response.status_code}")
            return False
    
    def send_to_feishu(self, content: str) -> bool:
        """
        推送消息到飛書機器人
        
        飛書自定義機器人 Webhook 消息格式：
        {
            "msg_type": "text",
            "content": {
                "text": "文本內容"
            }
        }
        
        說明：飛書文本消息不會渲染 Markdown，需使用交互卡片（lark_md）格式
        
        注意：飛書文本消息限制約 20KB，超長內容會自動分批發送
        可通過環境變量 FEISHU_MAX_BYTES 調整限制值
        
        Args:
            content: 消息內容（Markdown 會轉為純文本）
            
        Returns:
            是否發送成功
        """
        if not self._feishu_url:
            logger.warning("飛書 Webhook 未配置，跳過推送")
            return False
        
        # 飛書 lark_md 支持有限，先做格式轉換
        formatted_content = format_feishu_markdown(content)

        max_bytes = self._feishu_max_bytes  # 從配置讀取，默認 20000 字節
        
        # 檢查字節長度，超長則分批發送
        content_bytes = len(formatted_content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"飛書消息內容超長({content_bytes}字節/{len(content)}字符)，將分批發送")
            return self._send_feishu_chunked(formatted_content, max_bytes)
        
        try:
            return self._send_feishu_message(formatted_content)
        except Exception as e:
            logger.error(f"發送飛書消息失敗: {e}")
            return False
    
    def _send_feishu_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批發送長消息到飛書
        
        按股票分析塊（以 --- 或 ### 分隔）智能分割，確保每批不超過限制
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節數
            
        Returns:
            是否全部發送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            """獲取字符串的 UTF-8 字節數"""
            return len(s.encode('utf-8'))
        
        # 智能分割：優先按 "---" 分隔（股票之間的分隔線）
        # 如果沒有分隔線，按 "### " 標題分割（每隻股票的標題）
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            # 按 ### 分割，但保留 ### 前綴
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 無法智能分割，按行強制分割
            return self._send_feishu_force_chunked(content, max_bytes)
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            # 如果單個 section 就超長，需要強制截斷
            if section_bytes > max_bytes:
                # 先發送當前積累的內容
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0
                
                # 強制截斷這個超長 section（按字節截斷）
                truncated = self._truncate_to_bytes(section, max_bytes - 200)
                truncated += "\n\n...(本段內容過長已截斷)"
                chunks.append(truncated)
                continue
            
            # 檢查加入後是否超長
            if current_bytes + section_bytes > max_bytes:
                # 保存當前塊，開始新塊
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        # 添加最後一塊
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 分批發送
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"飛書分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分頁標記
            if total_chunks > 1:
                page_marker = f"\n\n📄 ({i+1}/{total_chunks})"
                chunk_with_marker = chunk + page_marker
            else:
                chunk_with_marker = chunk
            
            try:
                if self._send_feishu_message(chunk_with_marker):
                    success_count += 1
                    logger.info(f"飛書第 {i+1}/{total_chunks} 批發送成功")
                else:
                    logger.error(f"飛書第 {i+1}/{total_chunks} 批發送失敗")
            except Exception as e:
                logger.error(f"飛書第 {i+1}/{total_chunks} 批發送異常: {e}")
            
            # 批次間隔，避免觸發頻率限制
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_feishu_force_chunked(self, content: str, max_bytes: int) -> bool:
        """
        強制按字節分割發送（無法智能分割時的 fallback）
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節數
        """
        import time
        
        chunks = []
        current_chunk = ""
        
        # 按行分割，確保不會在多字節字符中間截斷
        lines = content.split('\n')
        
        for line in lines:
            test_chunk = current_chunk + ('\n' if current_chunk else '') + line
            if len(test_chunk.encode('utf-8')) > max_bytes - 100:  # 預留空間給分頁標記
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = test_chunk
        
        if current_chunk:
            chunks.append(current_chunk)
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"飛書強制分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            page_marker = f"\n\n📄 ({i+1}/{total_chunks})" if total_chunks > 1 else ""
            
            try:
                if self._send_feishu_message(chunk + page_marker):
                    success_count += 1
            except Exception as e:
                logger.error(f"飛書第 {i+1}/{total_chunks} 批發送異常: {e}")
            
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_feishu_message(self, content: str) -> bool:
        """發送單條飛書消息（優先使用 Markdown 卡片）"""
        def _post_payload(payload: Dict[str, Any]) -> bool:
            logger.debug(f"飛書請求 URL: {self._feishu_url}")
            logger.debug(f"飛書請求 payload 長度: {len(content)} 字符")

            response = requests.post(
                self._feishu_url,
                json=payload,
                timeout=30
            )

            logger.debug(f"飛書響應狀態碼: {response.status_code}")
            logger.debug(f"飛書響應內容: {response.text}")

            if response.status_code == 200:
                result = response.json()
                code = result.get('code') if 'code' in result else result.get('StatusCode')
                if code == 0:
                    logger.info("飛書消息發送成功")
                    return True
                else:
                    error_msg = result.get('msg') or result.get('StatusMessage', '未知錯誤')
                    error_code = result.get('code') or result.get('StatusCode', 'N/A')
                    logger.error(f"飛書返回錯誤 [code={error_code}]: {error_msg}")
                    logger.error(f"完整響應: {result}")
                    return False
            else:
                logger.error(f"飛書請求失敗: HTTP {response.status_code}")
                logger.error(f"響應內容: {response.text}")
                return False

        # 1) 優先使用交互卡片（支持 Markdown 渲染）
        card_payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "A股智能分析報告"
                    }
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    }
                ]
            }
        }

        if _post_payload(card_payload):
            return True

        # 2) 回退為普通文本消息
        text_payload = {
            "msg_type": "text",
            "content": {
                "text": content
            }
        }

        return _post_payload(text_payload)

    def send_to_email(self, content: str, subject: Optional[str] = None) -> bool:
        """
        通過 SMTP 發送郵件（自動識別 SMTP 服務器）
        
        Args:
            content: 郵件內容（支持 Markdown，會轉換為 HTML）
            subject: 郵件主題（可選，默認自動生成）
            
        Returns:
            是否發送成功
        """
        if not self._is_email_configured():
            logger.warning("郵件配置不完整，跳過推送")
            return False
        
        sender = self._email_config['sender']
        password = self._email_config['password']
        receivers = self._email_config['receivers']
        
        try:
            # 生成主題
            if subject is None:
                date_str = datetime.now().strftime('%Y-%m-%d')
                subject = f"📈 股票智能分析報告 - {date_str}"
            
            # 將 Markdown 轉換為簡單 HTML
            html_content = self._markdown_to_html(content)
            
            # 構建郵件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = formataddr((self._email_config.get('sender_name', '股票分析助手'), sender))
            msg['To'] = ', '.join(receivers)
            
            # 添加純文本和 HTML 兩個版本
            text_part = MIMEText(content, 'plain', 'utf-8')
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(text_part)
            msg.attach(html_part)
            
            # 自動識別 SMTP 配置
            domain = sender.split('@')[-1].lower()
            smtp_config = SMTP_CONFIGS.get(domain)
            
            if smtp_config:
                smtp_server = smtp_config['server']
                smtp_port = smtp_config['port']
                use_ssl = smtp_config['ssl']
                logger.info(f"自動識別郵箱類型: {domain} -> {smtp_server}:{smtp_port}")
            else:
                # 未知郵箱，嘗試通用配置
                smtp_server = f"smtp.{domain}"
                smtp_port = 465
                use_ssl = True
                logger.warning(f"未知郵箱類型 {domain}，嘗試通用配置: {smtp_server}:{smtp_port}")
            
            # 根據配置選擇連接方式
            if use_ssl:
                # SSL 連接（端口 465）
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
            else:
                # TLS 連接（端口 587）
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                server.starttls()
            
            server.login(sender, password)
            server.send_message(msg)
            server.quit()
            
            logger.info(f"郵件發送成功，收件人: {receivers}")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error("郵件發送失敗：認證錯誤，請檢查郵箱和授權碼是否正確")
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(f"郵件發送失敗：無法連接 SMTP 服務器 - {e}")
            return False
        except Exception as e:
            logger.error(f"發送郵件失敗: {e}")
            return False
    
    def _markdown_to_html(self, markdown_text: str) -> str:
        """
        將 Markdown 轉換為 HTML，支持表格並優化排版

        使用 markdown2 庫進行轉換，並添加優化的 CSS 樣式
        解決問題：
        1. 郵件表格未渲染問題
        2. 郵件內容排版過於鬆散問題
        """
        # 使用 markdown2 轉換，開啟表格和其他擴展支持
        html_content = markdown2.markdown(
            markdown_text,
            extras=["tables", "fenced-code-blocks", "break-on-newline", "cuddled-lists"]
        )

        # 優化 CSS 樣式：更緊湊的排版，美觀的表格
        css_style = """
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                line-height: 1.5;
                color: #24292e;
                font-size: 14px;
                padding: 15px;
                max-width: 900px;
                margin: 0 auto;
            }
            h1 {
                font-size: 20px;
                border-bottom: 1px solid #eaecef;
                padding-bottom: 0.3em;
                margin-top: 1.2em;
                margin-bottom: 0.8em;
                color: #0366d6;
            }
            h2 {
                font-size: 18px;
                border-bottom: 1px solid #eaecef;
                padding-bottom: 0.3em;
                margin-top: 1.0em;
                margin-bottom: 0.6em;
            }
            h3 {
                font-size: 16px;
                margin-top: 0.8em;
                margin-bottom: 0.4em;
            }
            p {
                margin-top: 0;
                margin-bottom: 8px;
            }
            /* 表格樣式優化 */
            table {
                border-collapse: collapse;
                width: 100%;
                margin: 12px 0;
                display: block;
                overflow-x: auto;
                font-size: 13px;
            }
            th, td {
                border: 1px solid #dfe2e5;
                padding: 6px 10px;
                text-align: left;
            }
            th {
                background-color: #f6f8fa;
                font-weight: 600;
            }
            tr:nth-child(2n) {
                background-color: #f8f8f8;
            }
            tr:hover {
                background-color: #f1f8ff;
            }
            /* 引用塊樣式 */
            blockquote {
                color: #6a737d;
                border-left: 0.25em solid #dfe2e5;
                padding: 0 1em;
                margin: 0 0 10px 0;
            }
            /* 代碼塊樣式 */
            code {
                padding: 0.2em 0.4em;
                margin: 0;
                font-size: 85%;
                background-color: rgba(27,31,35,0.05);
                border-radius: 3px;
                font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
            }
            pre {
                padding: 12px;
                overflow: auto;
                line-height: 1.45;
                background-color: #f6f8fa;
                border-radius: 3px;
                margin-bottom: 10px;
            }
            hr {
                height: 0.25em;
                padding: 0;
                margin: 16px 0;
                background-color: #e1e4e8;
                border: 0;
            }
            ul, ol {
                padding-left: 20px;
                margin-bottom: 10px;
            }
            li {
                margin: 2px 0;
            }
        """


        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {css_style}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
    
    def send_to_telegram(self, content: str) -> bool:
        """
        推送消息到 Telegram 機器人
        
        Telegram Bot API 格式：
        POST https://api.telegram.org/bot<token>/sendMessage
        {
            "chat_id": "xxx",
            "text": "消息內容",
            "parse_mode": "Markdown"
        }
        
        Args:
            content: 消息內容（Markdown 格式）
            
        Returns:
            是否發送成功
        """
        if not self._is_telegram_configured():
            logger.warning("Telegram 配置不完整，跳過推送")
            return False
        
        bot_token = self._telegram_config['bot_token']
        chat_id = self._telegram_config['chat_id']
        message_thread_id = self._telegram_config.get('message_thread_id')
        
        try:
            # Telegram API 端點
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            # Telegram 消息最大長度 4096 字符
            max_length = 4096
            
            if len(content) <= max_length:
                # 單條消息發送
                return self._send_telegram_message(api_url, chat_id, content, message_thread_id)
            else:
                # 分段發送長消息
                return self._send_telegram_chunked(api_url, chat_id, content, max_length, message_thread_id)
                
        except Exception as e:
            logger.error(f"發送 Telegram 消息失敗: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def _send_telegram_message(self, api_url: str, chat_id: str, text: str, message_thread_id: Optional[str] = None) -> bool:
        """發送單條 Telegram 消息"""
        # 轉換 Markdown 為 Telegram 支持的格式
        # Telegram 的 Markdown 格式稍有不同，做簡單處理
        telegram_text = self._convert_to_telegram_markdown(text)
        
        payload = {
            "chat_id": chat_id,
            "text": telegram_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }

        if message_thread_id:
            payload['message_thread_id'] = message_thread_id
        
        response = requests.post(api_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                logger.info("Telegram 消息發送成功")
                return True
            else:
                error_desc = result.get('description', '未知錯誤')
                logger.error(f"Telegram 返回錯誤: {error_desc}")
                
                # 如果 Markdown 解析失敗，嘗試純文本發送
                if 'parse' in error_desc.lower() or 'markdown' in error_desc.lower():
                    logger.info("嘗試使用純文本格式重新發送...")
                    payload['parse_mode'] = None
                    payload['text'] = text  # 使用原始文本
                    del payload['parse_mode']
                    
                    response = requests.post(api_url, json=payload, timeout=10)
                    if response.status_code == 200 and response.json().get('ok'):
                        logger.info("Telegram 消息發送成功（純文本）")
                        return True
                
                return False
        else:
            logger.error(f"Telegram 請求失敗: HTTP {response.status_code}")
            logger.error(f"響應內容: {response.text}")
            return False
    
    def _send_telegram_chunked(self, api_url: str, chat_id: str, content: str, max_length: int, message_thread_id: Optional[str] = None) -> bool:
        """分段發送長 Telegram 消息"""
        # 按段落分割
        sections = content.split("\n---\n")
        
        current_chunk = []
        current_length = 0
        all_success = True
        chunk_index = 1
        
        for section in sections:
            section_length = len(section) + 5  # +5 for "\n---\n"
            
            if current_length + section_length > max_length:
                # 發送當前塊
                if current_chunk:
                    chunk_content = "\n---\n".join(current_chunk)
                    logger.info(f"發送 Telegram 消息塊 {chunk_index}...")
                    if not self._send_telegram_message(api_url, chat_id, chunk_content, message_thread_id):
                        all_success = False
                    chunk_index += 1
                
                # 重置
                current_chunk = [section]
                current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length
        
        # 發送最後一塊
        if current_chunk:
            chunk_content = "\n---\n".join(current_chunk)
            logger.info(f"發送 Telegram 消息塊 {chunk_index}...")
            if not self._send_telegram_message(api_url, chat_id, chunk_content, message_thread_id):
                all_success = False
                
        return all_success
    
    def _convert_to_telegram_markdown(self, text: str) -> str:
        """
        將標準 Markdown 轉換為 Telegram 支持的格式
        
        Telegram Markdown 限制：
        - 不支持 # 標題
        - 使用 *bold* 而非 **bold**
        - 使用 _italic_ 
        """
        result = text
        
        # 移除 # 標題標記（Telegram 不支持）
        result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)
        
        # 轉換 **bold** 為 *bold*
        result = re.sub(r'\*\*(.+?)\*\*', r'*\1*', result)
        
        # 轉義特殊字符（Telegram Markdown 需要）
        # 注意：不轉義已經用於格式的 * _ `
        for char in ['[', ']', '(', ')']:
            result = result.replace(char, f'\\{char}')
        
        return result
    
    def send_to_pushover(self, content: str, title: Optional[str] = None) -> bool:
        """
        推送消息到 Pushover
        
        Pushover API 格式：
        POST https://api.pushover.net/1/messages.json
        {
            "token": "應用 API Token",
            "user": "用戶 Key",
            "message": "消息內容",
            "title": "標題（可選）"
        }
        
        Pushover 特點：
        - 支持 iOS/Android/桌面多平臺推送
        - 消息限制 1024 字符
        - 支持優先級設置
        - 支持 HTML 格式
        
        Args:
            content: 消息內容（Markdown 格式，會轉為純文本）
            title: 消息標題（可選，默認為"股票分析報告"）
            
        Returns:
            是否發送成功
        """
        if not self._is_pushover_configured():
            logger.warning("Pushover 配置不完整，跳過推送")
            return False
        
        user_key = self._pushover_config['user_key']
        api_token = self._pushover_config['api_token']
        
        # Pushover API 端點
        api_url = "https://api.pushover.net/1/messages.json"
        
        # 處理消息標題
        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析報告 - {date_str}"
        
        # Pushover 消息限制 1024 字符
        max_length = 1024
        
        # 轉換 Markdown 為純文本（Pushover 支持 HTML，但純文本更通用）
        plain_content = self._markdown_to_plain_text(content)
        
        if len(plain_content) <= max_length:
            # 單條消息發送
            return self._send_pushover_message(api_url, user_key, api_token, plain_content, title)
        else:
            # 分段發送長消息
            return self._send_pushover_chunked(api_url, user_key, api_token, plain_content, title, max_length)
    
    def _markdown_to_plain_text(self, markdown_text: str) -> str:
        """
        將 Markdown 轉換為純文本
        
        移除 Markdown 格式標記，保留可讀性
        """
        text = markdown_text
        
        # 移除標題標記 # ## ###
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        
        # 移除加粗 **text** -> text
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        
        # 移除斜體 *text* -> text
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        
        # 移除引用 > text -> text
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        
        # 移除列表標記 - item -> item
        text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)
        
        # 移除分隔線 ---
        text = re.sub(r'^---+$', '────────', text, flags=re.MULTILINE)
        
        # 移除表格語法 |---|---|
        text = re.sub(r'\|[-:]+\|[-:|\s]+\|', '', text)
        text = re.sub(r'^\|(.+)\|$', r'\1', text, flags=re.MULTILINE)
        
        # 清理多餘空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()
    
    def _send_pushover_message(
        self, 
        api_url: str, 
        user_key: str, 
        api_token: str, 
        message: str, 
        title: str,
        priority: int = 0
    ) -> bool:
        """
        發送單條 Pushover 消息
        
        Args:
            api_url: Pushover API 端點
            user_key: 用戶 Key
            api_token: 應用 API Token
            message: 消息內容
            title: 消息標題
            priority: 優先級 (-2 ~ 2，默認 0)
        """
        try:
            payload = {
                "token": api_token,
                "user": user_key,
                "message": message,
                "title": title,
                "priority": priority,
            }
            
            response = requests.post(api_url, data=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 1:
                    logger.info("Pushover 消息發送成功")
                    return True
                else:
                    errors = result.get('errors', ['未知錯誤'])
                    logger.error(f"Pushover 返回錯誤: {errors}")
                    return False
            else:
                logger.error(f"Pushover 請求失敗: HTTP {response.status_code}")
                logger.debug(f"響應內容: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"發送 Pushover 消息失敗: {e}")
            return False
    
    def _send_pushover_chunked(
        self, 
        api_url: str, 
        user_key: str, 
        api_token: str, 
        content: str, 
        title: str,
        max_length: int
    ) -> bool:
        """
        分段發送長 Pushover 消息
        
        按段落分割，確保每段不超過最大長度
        """
        import time
        
        # 按段落（分隔線或雙換行）分割
        if "────────" in content:
            sections = content.split("────────")
            separator = "────────"
        else:
            sections = content.split("\n\n")
            separator = "\n\n"
        
        chunks = []
        current_chunk = []
        current_length = 0
        
        for section in sections:
            # 計算添加這個 section 後的實際長度
            # join() 只在元素之間放置分隔符，不是每個元素後面
            # 所以：第一個元素不需要分隔符，後續元素需要一個分隔符連接
            if current_chunk:
                # 已有元素，添加新元素需要：當前長度 + 分隔符 + 新 section
                new_length = current_length + len(separator) + len(section)
            else:
                # 第一個元素，不需要分隔符
                new_length = len(section)
            
            if new_length > max_length:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_length = len(section)
            else:
                current_chunk.append(section)
                current_length = new_length
        
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"Pushover 分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分頁標記到標題
            chunk_title = f"{title} ({i+1}/{total_chunks})" if total_chunks > 1 else title
            
            if self._send_pushover_message(api_url, user_key, api_token, chunk, chunk_title):
                success_count += 1
                logger.info(f"Pushover 第 {i+1}/{total_chunks} 批發送成功")
            else:
                logger.error(f"Pushover 第 {i+1}/{total_chunks} 批發送失敗")
            
            # 批次間隔，避免觸發頻率限制
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def send_to_custom(self, content: str) -> bool:
        """
        推送消息到自定義 Webhook
        
        支持任意接受 POST JSON 的 Webhook 端點
        默認發送格式：{"text": "消息內容", "content": "消息內容"}
        
        適用於：
        - 釘釘機器人
        - Discord Webhook
        - Slack Incoming Webhook
        - 自建通知服務
        - 其他支持 POST JSON 的服務
        
        Args:
            content: 消息內容（Markdown 格式）
            
        Returns:
            是否至少有一個 Webhook 發送成功
        """
        if not self._custom_webhook_urls:
            logger.warning("未配置自定義 Webhook，跳過推送")
            return False
        
        success_count = 0
        
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                # 通用 JSON 格式，兼容大多數 Webhook
                # 釘釘格式: {"msgtype": "text", "text": {"content": "xxx"}}
                # Slack 格式: {"text": "xxx"}
                # Discord 格式: {"content": "xxx"}
                
                # 釘釘機器人對 body 有字節上限（約 20000 bytes），超長需要分批發送
                if self._is_dingtalk_webhook(url):
                    if self._send_dingtalk_chunked(url, content, max_bytes=20000):
                        logger.info(f"自定義 Webhook {i+1}（釘釘）推送成功")
                        success_count += 1
                    else:
                        logger.error(f"自定義 Webhook {i+1}（釘釘）推送失敗")
                    continue

                # 其他 Webhook：單次發送
                payload = self._build_custom_webhook_payload(url, content)
                if self._post_custom_webhook(url, payload, timeout=30):
                    logger.info(f"自定義 Webhook {i+1} 推送成功")
                    success_count += 1
                else:
                    logger.error(f"自定義 Webhook {i+1} 推送失敗")
                    
            except Exception as e:
                logger.error(f"自定義 Webhook {i+1} 推送異常: {e}")
        
        logger.info(f"自定義 Webhook 推送完成：成功 {success_count}/{len(self._custom_webhook_urls)}")
        return success_count > 0

    @staticmethod
    def _is_dingtalk_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower

    def _post_custom_webhook(self, url: str, payload: dict, timeout: int = 30) -> bool:
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        # 支持 Bearer Token 認證（#51）
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        response = requests.post(url, data=body, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return True
        logger.error(f"自定義 Webhook 推送失敗: HTTP {response.status_code}")
        logger.debug(f"響應內容: {response.text[:200]}")
        return False

    def _chunk_markdown_by_bytes(self, content: str, max_bytes: int) -> List[str]:
        def get_bytes(s: str) -> int:
            return len(s.encode('utf-8'))

        def split_by_bytes(text: str, limit: int) -> List[str]:
            parts: List[str] = []
            remaining = text
            while remaining:
                part = self._truncate_to_bytes(remaining, limit)
                if not part:
                    break
                parts.append(part)
                remaining = remaining[len(part):]
            return parts

        # 優先按分隔線/標題分割，保證分頁自然
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # fallback：按行拼接
            sections = content.split("\n")
            separator = "\n"

        chunks: List[str] = []
        current_chunk: List[str] = []
        current_bytes = 0
        sep_bytes = get_bytes(separator)

        for section in sections:
            section_bytes = get_bytes(section)
            extra = sep_bytes if current_chunk else 0

            # 單段超長：截斷
            if section_bytes + extra > max_bytes:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0

                # 無法按結構拆分時，按字節強制拆分，避免整段被截斷丟失
                for part in split_by_bytes(section, max(200, max_bytes - 200)):
                    chunks.append(part)
                continue

            if current_bytes + section_bytes + extra > max_bytes:
                chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                if current_chunk:
                    current_bytes += sep_bytes
                current_chunk.append(section)
                current_bytes += section_bytes

        if current_chunk:
            chunks.append(separator.join(current_chunk))

        # 移除空塊
        return [c for c in (c.strip() for c in chunks) if c]

    def _send_dingtalk_chunked(self, url: str, content: str, max_bytes: int = 20000) -> bool:
        import time as _time

        # 為 payload 開銷預留空間，避免 body 超限
        budget = max(1000, max_bytes - 1500)
        chunks = self._chunk_markdown_by_bytes(content, budget)
        if not chunks:
            return False

        total = len(chunks)
        ok = 0

        for idx, chunk in enumerate(chunks):
            marker = f"\n\n📄 *({idx+1}/{total})*" if total > 1 else ""
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析報告",
                    "text": chunk + marker,
                },
            }

            # 如果仍超限（極端情況下），再按字節硬截斷一次
            body_bytes = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            if body_bytes > max_bytes:
                hard_budget = max(200, budget - (body_bytes - max_bytes) - 200)
                payload["markdown"]["text"] = self._truncate_to_bytes(payload["markdown"]["text"], hard_budget)

            if self._post_custom_webhook(url, payload, timeout=30):
                ok += 1
            else:
                logger.error(f"釘釘分批發送失敗: 第 {idx+1}/{total} 批")

            if idx < total - 1:
                _time.sleep(1)

        return ok == total
    
    def _build_custom_webhook_payload(self, url: str, content: str) -> dict:
        """
        根據 URL 構建對應的 Webhook payload
        
        自動識別常見服務並使用對應格式
        """
        url_lower = url.lower()
        
        # 釘釘機器人
        if 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析報告",
                    "text": content
                }
            }
        
        # Discord Webhook（使用 Embed 格式）
        if 'discord.com/api/webhooks' in url_lower or 'discordapp.com/api/webhooks' in url_lower:
            discord_content = self._convert_to_discord_markdown(content)
            # Embed description 限制 4096 字元
            truncated = discord_content[:4000] + "..." if len(discord_content) > 4000 else discord_content
            date_str = datetime.now().strftime('%Y-%m-%d')
            return {
                "embeds": [{
                    "title": f"股票分析報告 - {date_str}",
                    "description": truncated,
                    "color": 0x2F80ED,
                    "footer": {"text": "由 A股分析機器人 生成"},
                    "timestamp": datetime.now().isoformat()
                }]
            }
        
        # Slack Incoming Webhook
        if 'hooks.slack.com' in url_lower:
            return {
                "text": content,
                "mrkdwn": True
            }
        
        # Bark (iOS 推送)
        if 'api.day.app' in url_lower:
            return {
                "title": "股票分析報告",
                "body": content[:4000],  # Bark 限制
                "group": "stock"
            }
        
        # 通用格式（兼容大多數服務）
        return {
            "text": content,
            "content": content,
            "message": content,
            "body": content
        }

    def _send_via_source_context(self, content: str) -> bool:
        """
        使用消息上下文（如釘釘/飛書會話）發送一份報告
        
        主要用於從機器人 Stream 模式觸發的任務，確保結果能回到觸發的會話。
        """
        success = False
        
        # 嘗試釘釘會話
        session_webhook = self._extract_dingtalk_session_webhook()
        if session_webhook:
            try:
                if self._send_dingtalk_chunked(session_webhook, content, max_bytes=20000):
                    logger.info("已通過釘釘會話（Stream）推送報告")
                    success = True
                else:
                    logger.error("釘釘會話（Stream）推送失敗")
            except Exception as e:
                logger.error(f"釘釘會話（Stream）推送異常: {e}")

        # 嘗試飛書會話
        feishu_info = self._extract_feishu_reply_info()
        if feishu_info:
            try:
                if self._send_feishu_stream_reply(feishu_info["chat_id"], content):
                    logger.info("已通過飛書會話（Stream）推送報告")
                    success = True
                else:
                    logger.error("飛書會話（Stream）推送失敗")
            except Exception as e:
                logger.error(f"飛書會話（Stream）推送異常: {e}")

        return success

    def _send_feishu_stream_reply(self, chat_id: str, content: str) -> bool:
        """
        通過飛書 Stream 模式發送消息到指定會話
        
        Args:
            chat_id: 飛書會話 ID
            content: 消息內容
            
        Returns:
            是否發送成功
        """
        try:
            from bot.platforms.feishu_stream import FeishuReplyClient, FEISHU_SDK_AVAILABLE
            if not FEISHU_SDK_AVAILABLE:
                logger.warning("飛書 SDK 不可用，無法發送 Stream 回覆")
                return False
            
            from src.config import get_config
            config = get_config()
            
            app_id = getattr(config, 'feishu_app_id', None)
            app_secret = getattr(config, 'feishu_app_secret', None)
            
            if not app_id or not app_secret:
                logger.warning("飛書 APP_ID 或 APP_SECRET 未配置")
                return False
            
            # 創建回覆客戶端
            reply_client = FeishuReplyClient(app_id, app_secret)
            
            # 飛書文本消息有長度限制，需要分批發送
            max_bytes = getattr(config, 'feishu_max_bytes', 20000)
            content_bytes = len(content.encode('utf-8'))
            
            if content_bytes > max_bytes:
                return self._send_feishu_stream_chunked(reply_client, chat_id, content, max_bytes)
            
            return reply_client.send_to_chat(chat_id, content)
            
        except ImportError as e:
            logger.error(f"導入飛書 Stream 模塊失敗: {e}")
            return False
        except Exception as e:
            logger.error(f"飛書 Stream 回覆異常: {e}")
            return False

    def _send_feishu_stream_chunked(
        self, 
        reply_client, 
        chat_id: str, 
        content: str, 
        max_bytes: int
    ) -> bool:
        """
        分批發送長消息到飛書（Stream 模式）
        
        Args:
            reply_client: FeishuReplyClient 實例
            chat_id: 飛書會話 ID
            content: 完整消息內容
            max_bytes: 單條消息最大字節數
            
        Returns:
            是否全部發送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            return len(s.encode('utf-8'))
        
        # 按段落或分隔線分割
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 按行分割
            sections = content.split("\n")
            separator = "\n"
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            if current_bytes + section_bytes > max_bytes:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 發送每個分塊
        success = True
        for i, chunk in enumerate(chunks):
            if i > 0:
                time.sleep(0.5)  # 避免請求過快
            
            if not reply_client.send_to_chat(chat_id, chunk):
                success = False
                logger.error(f"飛書 Stream 分塊 {i+1}/{len(chunks)} 發送失敗")
        
        return success
    
    def send_to_pushplus(self, content: str, title: Optional[str] = None) -> bool:
        """
        推送消息到 PushPlus

        PushPlus API 格式：
        POST http://www.pushplus.plus/send
        {
            "token": "用戶令牌",
            "title": "消息標題",
            "content": "消息內容",
            "template": "html/txt/json/markdown"
        }

        PushPlus 特點：
        - 國內推送服務，免費額度充足
        - 支持微信公眾號推送
        - 支持多種消息格式

        Args:
            content: 消息內容（Markdown 格式）
            title: 消息標題（可選）

        Returns:
            是否發送成功
        """
        if not self._pushplus_token:
            logger.warning("PushPlus Token 未配置，跳過推送")
            return False

        # PushPlus API 端點
        api_url = "http://www.pushplus.plus/send"

        # 處理消息標題
        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析報告 - {date_str}"

        try:
            payload = {
                "token": self._pushplus_token,
                "title": title,
                "content": content,
                "template": "markdown"  # 使用 Markdown 格式
            }

            response = requests.post(api_url, json=payload, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 200:
                    logger.info("PushPlus 消息發送成功")
                    return True
                else:
                    error_msg = result.get('msg', '未知錯誤')
                    logger.error(f"PushPlus 返回錯誤: {error_msg}")
                    return False
            else:
                logger.error(f"PushPlus 請求失敗: HTTP {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"發送 PushPlus 消息失敗: {e}")
            return False

    def send_to_serverchan3(self, content: str, title: Optional[str] = None) -> bool:
        """
        推送消息到 Server醬3

        Server醬3 API 格式：
        POST https://sctapi.ftqq.com/{sendkey}.send
        或
        POST https://{num}.push.ft07.com/send/{sendkey}.send
        {
            "title": "消息標題",
            "desp": "消息內容",
            "options": {}
        }

        Server醬3 特點：
        - 國內推送服務，支持多家國產系統推送通道，可無後台推送
        - 簡單易用的 API 接口

        Args:
            content: 消息內容（Markdown 格式）
            title: 消息標題（可選）

        Returns:
            是否發送成功
        """
        if not self._serverchan3_sendkey:
            logger.warning("Server醬3 SendKey 未配置，跳過推送")
            return False

        # 處理消息標題
        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析報告 - {date_str}"

        try:
            # 根據 sendkey 格式構造 URL
            sendkey = self._serverchan3_sendkey
            if sendkey.startswith('sctp'):
                match = re.match(r'sctp(\d+)t', sendkey)
                if match:
                    num = match.group(1)
                    url = f"https://{num}.push.ft07.com/send/{sendkey}.send"
                else:
                    logger.error("Invalid sendkey format for sctp")
                    return False
            else:
                url = f"https://sctapi.ftqq.com/{sendkey}.send"

            # 構建請求參數
            params = {
                'title': title,
                'desp': content,
                'options': {}
            }

            # 發送請求
            headers = {
                'Content-Type': 'application/json;charset=utf-8'
            }
            response = requests.post(url, json=params, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Server醬3 消息發送成功: {result}")
                return True
            else:
                logger.error(f"Server醬3 請求失敗: HTTP {response.status_code}")
                logger.error(f"響應內容: {response.text}")
                return False

        except Exception as e:
            logger.error(f"發送 Server醬3 消息失敗: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False


   
    def send_to_discord(self, content: str) -> bool:
        """
        推送消息到 Discord（支持 Webhook 和 Bot API）
        
        Args:
            content: Markdown 格式的消息內容
            
        Returns:
            是否發送成功
        """
        # 優先使用 Webhook（配置簡單，權限低）
        if self._discord_config['webhook_url']:
            return self._send_discord_webhook(content)
        
        # 其次使用 Bot API（權限高，需要 channel_id）
        if self._discord_config['bot_token'] and self._discord_config['channel_id']:
            return self._send_discord_bot(content)
        
        logger.warning("Discord 配置不完整，跳過推送")
        return False


    def send_to_astrbot(self, content: str) -> bool:
        """
        推送消息到 AstrBot（通過適配器支持）

        Args:
            content: Markdown 格式的消息內容

        Returns:
            是否發送成功
        """
        if self._astrbot_config['astrbot_url']:
            return self._send_astrbot(content)

        logger.warning("AstrBot 配置不完整，跳過推送")
        return False
    
    def _convert_to_discord_markdown(self, text: str) -> str:
        """
        將標準 Markdown 轉換為 Discord 支持的格式

        Discord Markdown 限制：
        - 不支持表格語法
        - 支持 # ## ### 標題（會加粗顯示）
        - 支持 **bold** *italic* ~~strikethrough~~
        - 支持 > 引用、``` 代碼塊、- 列表
        """
        result = text

        # 轉換表格為易讀的純文字格式
        lines = result.split('\n')
        converted_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # 偵測表格分隔行 |---|---|
            if re.match(r'^\|[-:\s|]+\|$', line):
                i += 1
                continue
            # 轉換表格資料行 | a | b | -> a | b
            if re.match(r'^\|(.+)\|$', line):
                cells = [c.strip() for c in line.strip('|').split('|')]
                converted_lines.append('  '.join(cells))
            else:
                converted_lines.append(line)
            i += 1

        result = '\n'.join(converted_lines)

        # 清理多餘空行
        result = re.sub(r'\n{3,}', '\n\n', result)

        return result.strip()

    def _split_discord_content(self, content: str, max_length: int = 4000) -> list:
        """
        將長內容按段落分割為多個片段，每段不超過 max_length

        Args:
            content: 完整內容
            max_length: 每段最大字元數（Embed description 限制 4096）

        Returns:
            分割後的內容列表
        """
        if len(content) <= max_length:
            return [content]

        chunks = []
        # 優先按 --- 分隔線分割
        sections = content.split('\n---\n')

        current_chunk = []
        current_length = 0

        for section in sections:
            section_text = section.strip()
            # +5 for "\n---\n" separator
            if current_length + len(section_text) + 5 > max_length and current_chunk:
                chunks.append('\n---\n'.join(current_chunk))
                current_chunk = []
                current_length = 0

            # 如果單個 section 就超過限制，按行分割
            if len(section_text) > max_length:
                if current_chunk:
                    chunks.append('\n---\n'.join(current_chunk))
                    current_chunk = []
                    current_length = 0

                lines = section_text.split('\n')
                line_chunk = []
                line_length = 0
                for line in lines:
                    if line_length + len(line) + 1 > max_length and line_chunk:
                        chunks.append('\n'.join(line_chunk))
                        line_chunk = []
                        line_length = 0
                    line_chunk.append(line)
                    line_length += len(line) + 1
                if line_chunk:
                    current_chunk = ['\n'.join(line_chunk)]
                    current_length = line_length
            else:
                current_chunk.append(section_text)
                current_length += len(section_text) + 5

        if current_chunk:
            chunks.append('\n---\n'.join(current_chunk))

        return chunks

    def _send_discord_webhook(self, content: str) -> bool:
        """
        使用 Webhook 發送消息到 Discord（使用 Embed 格式）

        Discord Embed 支持更好的 Markdown 渲染，description 上限 4096 字元

        Args:
            content: Markdown 格式的消息內容

        Returns:
            是否發送成功
        """
        try:
            discord_content = self._convert_to_discord_markdown(content)
            chunks = self._split_discord_content(discord_content)

            all_success = True
            for i, chunk in enumerate(chunks):
                embed = {
                    'description': chunk,
                    'color': 0x2F80ED,  # 藍色
                }
                # 第一個 embed 加上標題
                if i == 0:
                    date_str = datetime.now().strftime('%Y-%m-%d')
                    embed['title'] = f'股票分析報告 - {date_str}'
                # 最後一個 embed 加上 footer
                if i == len(chunks) - 1:
                    embed['footer'] = {'text': f'由 A股分析機器人 生成'}
                    embed['timestamp'] = datetime.now().isoformat()

                payload = {
                    'username': 'A股分析機器人',
                    'avatar_url': 'https://picsum.photos/200',
                    'embeds': [embed]
                }

                response = requests.post(
                    self._discord_config['webhook_url'],
                    json=payload,
                    timeout=10
                )

                if response.status_code not in [200, 204]:
                    logger.error(f"Discord Webhook 發送失敗 (chunk {i+1}/{len(chunks)}): {response.status_code} {response.text}")
                    all_success = False

            if all_success:
                logger.info(f"Discord Webhook 消息發送成功（共 {len(chunks)} 段）")
            return all_success
        except Exception as e:
            logger.error(f"Discord Webhook 發送異常: {e}")
            return False
    
    def _send_discord_bot(self, content: str) -> bool:
        """
        使用 Bot API 發送消息到 Discord（使用 Embed 格式）

        Args:
            content: Markdown 格式的消息內容

        Returns:
            是否發送成功
        """
        try:
            headers = {
                'Authorization': f'Bot {self._discord_config["bot_token"]}',
                'Content-Type': 'application/json'
            }

            discord_content = self._convert_to_discord_markdown(content)
            chunks = self._split_discord_content(discord_content)

            url = f'https://discord.com/api/v10/channels/{self._discord_config["channel_id"]}/messages'
            all_success = True

            for i, chunk in enumerate(chunks):
                embed = {
                    'description': chunk,
                    'color': 0x2F80ED,
                }
                if i == 0:
                    date_str = datetime.now().strftime('%Y-%m-%d')
                    embed['title'] = f'股票分析報告 - {date_str}'
                if i == len(chunks) - 1:
                    embed['footer'] = {'text': '由 A股分析機器人 生成'}
                    embed['timestamp'] = datetime.now().isoformat()

                payload = {
                    'embeds': [embed]
                }

                response = requests.post(url, json=payload, headers=headers, timeout=10)

                if response.status_code != 200:
                    logger.error(f"Discord Bot 發送失敗 (chunk {i+1}/{len(chunks)}): {response.status_code} {response.text}")
                    all_success = False

            if all_success:
                logger.info(f"Discord Bot 消息發送成功（共 {len(chunks)} 段）")
            return all_success
        except Exception as e:
            logger.error(f"Discord Bot 發送異常: {e}")
            return False

    def _send_astrbot(self, content: str) -> bool:
        import time
        """
        使用 Bot API 發送消息到 AstrBot

        Args:
            content: Markdown 格式的消息內容

        Returns:
            是否發送成功
        """

        html_content = self._markdown_to_html(content)

        try:
            payload = {
                'content': html_content
            }
            signature =  ""
            timestamp = str(int(time.time()))
            if self._astrbot_config['astrbot_token']:
                """計算請求簽名"""
                payload_json = json.dumps(payload, sort_keys=True)
                sign_data = f"{timestamp}.{payload_json}".encode('utf-8')
                key = self._astrbot_config['astrbot_token']
                signature = hmac.new(
                    key.encode('utf-8'),
                    sign_data,
                    hashlib.sha256
                ).hexdigest()
            url = self._astrbot_config['astrbot_url']
            response = requests.post(url, json=payload, timeout=10,headers={
                        "Content-Type": "application/json",
                        "X-Signature": signature,
                        "X-Timestamp": timestamp
                    })

            if response.status_code == 200:
                logger.info("AstrBot 消息發送成功")
                return True
            else:
                logger.error(f"AstrBot 發送失敗: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"AstrBot 發送異常: {e}")
            return False
    
    def send(self, content: str) -> bool:
        """
        統一發送接口 - 向所有已配置的渠道發送
        
        遍歷所有已配置的渠道，逐一發送消息
        
        Args:
            content: 消息內容（Markdown 格式）
            
        Returns:
            是否至少有一個渠道發送成功
        """
        context_success = self.send_to_context(content)

        if not self._available_channels:
            if context_success:
                logger.info("已通過消息上下文渠道完成推送（無其他通知渠道）")
                return True
            logger.warning("通知服務不可用，跳過推送")
            return False
        
        channel_names = self.get_channel_names()
        logger.info(f"正在向 {len(self._available_channels)} 個渠道發送通知：{channel_names}")
        
        success_count = 0
        fail_count = 0
        
        for channel in self._available_channels:
            channel_name = ChannelDetector.get_channel_name(channel)
            try:
                if channel == NotificationChannel.WECHAT:
                    result = self.send_to_wechat(content)
                elif channel == NotificationChannel.FEISHU:
                    result = self.send_to_feishu(content)
                elif channel == NotificationChannel.TELEGRAM:
                    result = self.send_to_telegram(content)
                elif channel == NotificationChannel.EMAIL:
                    result = self.send_to_email(content)
                elif channel == NotificationChannel.PUSHOVER:
                    result = self.send_to_pushover(content)
                elif channel == NotificationChannel.PUSHPLUS:
                    result = self.send_to_pushplus(content)
                elif channel == NotificationChannel.SERVERCHAN3:
                    result = self.send_to_serverchan3(content)
                elif channel == NotificationChannel.CUSTOM:
                    result = self.send_to_custom(content)
                elif channel == NotificationChannel.DISCORD:
                    result = self.send_to_discord(content)
                elif channel == NotificationChannel.ASTRBOT:
                    result = self.send_to_astrbot(content)
                else:
                    logger.warning(f"不支持的通知渠道: {channel}")
                    result = False
                
                if result:
                    success_count += 1
                else:
                    fail_count += 1
                    
            except Exception as e:
                logger.error(f"{channel_name} 發送失敗: {e}")
                fail_count += 1
        
        logger.info(f"通知發送完成：成功 {success_count} 個，失敗 {fail_count} 個")
        return success_count > 0 or context_success
    
    def _send_chunked_messages(self, content: str, max_length: int) -> bool:
        """
        分段發送長消息
        
        按段落（---）分割，確保每段不超過最大長度
        """
        # 按分隔線分割
        sections = content.split("\n---\n")
        
        current_chunk = []
        current_length = 0
        all_success = True
        chunk_index = 1
        
        for section in sections:
            section_with_divider = section + "\n---\n"
            section_length = len(section_with_divider)
            
            if current_length + section_length > max_length:
                # 發送當前塊
                if current_chunk:
                    chunk_content = "\n---\n".join(current_chunk)
                    logger.info(f"發送消息塊 {chunk_index}...")
                    if not self.send(chunk_content):
                        all_success = False
                    chunk_index += 1
                
                # 重置
                current_chunk = [section]
                current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length
        
        # 發送最後一塊
        if current_chunk:
            chunk_content = "\n---\n".join(current_chunk)
            logger.info(f"發送消息塊 {chunk_index}（最後）...")
            if not self.send(chunk_content):
                all_success = False
        
        return all_success
    
    def save_report_to_file(
        self, 
        content: str, 
        filename: Optional[str] = None
    ) -> str:
        """
        保存日報到本地文件
        
        Args:
            content: 日報內容
            filename: 文件名（可選，默認按日期生成）
            
        Returns:
            保存的文件路徑
        """
        from pathlib import Path
        
        if filename is None:
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"report_{date_str}.md"
        
        # 確保 reports 目錄存在（使用項目根目錄下的 reports）
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = reports_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"日報已保存到: {filepath}")
        return str(filepath)


class NotificationBuilder:
    """
    通知消息構建器
    
    提供便捷的消息構建方法
    """
    
    @staticmethod
    def build_simple_alert(
        title: str,
        content: str,
        alert_type: str = "info"
    ) -> str:
        """
        構建簡單的提醒消息
        
        Args:
            title: 標題
            content: 內容
            alert_type: 類型（info, warning, error, success）
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        emoji = emoji_map.get(alert_type, "📢")
        
        return f"{emoji} **{title}**\n\n{content}"
    
    @staticmethod
    def build_stock_summary(results: List[AnalysisResult]) -> str:
        """
        構建股票摘要（簡短版）
        
        適用於快速通知
        """
        lines = ["📊 **今日自選股摘要**", ""]
        
        for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
            emoji = r.get_emoji()
            lines.append(f"{emoji} {r.name}({r.code}): {r.operation_advice} | 評分 {r.sentiment_score}")
        
        return "\n".join(lines)


# 便捷函數
def get_notification_service() -> NotificationService:
    """獲取通知服務實例"""
    return NotificationService()


def send_daily_report(results: List[AnalysisResult]) -> bool:
    """
    發送每日報告的快捷方式
    
    自動識別渠道並推送
    """
    service = get_notification_service()
    
    # 生成報告
    report = service.generate_daily_report(results)
    
    # 保存到本地
    service.save_report_to_file(report)
    
    # 推送到配置的渠道（自動識別）
    return service.send(report)


if __name__ == "__main__":
    # 測試代碼
    logging.basicConfig(level=logging.DEBUG)
    
    # 模擬分析結果
    test_results = [
        AnalysisResult(
            code='600519',
            name='貴州茅臺',
            sentiment_score=75,
            trend_prediction='看多',
            analysis_summary='技術面強勢，消息面利好',
            operation_advice='買入',
            technical_analysis='放量突破 MA20，MACD 金叉',
            news_summary='公司發佈分紅公告，業績超預期',
        ),
        AnalysisResult(
            code='000001',
            name='平安銀行',
            sentiment_score=45,
            trend_prediction='震盪',
            analysis_summary='橫盤整理，等待方向',
            operation_advice='持有',
            technical_analysis='均線粘合，成交量萎縮',
            news_summary='近期無重大消息',
        ),
        AnalysisResult(
            code='300750',
            name='寧德時代',
            sentiment_score=35,
            trend_prediction='看空',
            analysis_summary='技術面走弱，注意風險',
            operation_advice='賣出',
            technical_analysis='跌破 MA10 支撐，量能不足',
            news_summary='行業競爭加劇，毛利率承壓',
        ),
    ]
    
    service = NotificationService()
    
    # 顯示檢測到的渠道
    print("=== 通知渠道檢測 ===")
    print(f"當前渠道: {service.get_channel_names()}")
    print(f"渠道列表: {service.get_available_channels()}")
    print(f"服務可用: {service.is_available()}")
    
    # 生成日報
    print("\n=== 生成日報測試 ===")
    report = service.generate_daily_report(test_results)
    print(report)
    
    # 保存到文件
    print("\n=== 保存日報 ===")
    filepath = service.save_report_to_file(report)
    print(f"保存成功: {filepath}")
    
    # 推送測試
    if service.is_available():
        print(f"\n=== 推送測試（{service.get_channel_names()}）===")
        success = service.send(report)
        print(f"推送結果: {'成功' if success else '失敗'}")
    else:
        print("\n通知渠道未配置，跳過推送測試")
