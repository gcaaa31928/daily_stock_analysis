/**
 * 股票分析相關類型定義
 * 與 API 規範 (api_spec.json) 對齊
 */

// ============ 請求類型 ============

export interface AnalysisRequest {
  stockCode: string;
  reportType?: 'simple' | 'detailed';
  forceRefresh?: boolean;
  asyncMode?: boolean;
}

// ============ 報告類型 ============

/** 報告元資訊 */
export interface ReportMeta {
  queryId: string;
  stockCode: string;
  stockName: string;
  reportType: 'simple' | 'detailed';
  createdAt: string;
  currentPrice?: number;
  changePct?: number;
}

/** 情緒標籤 */
export type SentimentLabel = '極度悲觀' | '悲觀' | '中性' | '樂觀' | '極度樂觀';

/** 報告概覽區 */
export interface ReportSummary {
  analysisSummary: string;
  operationAdvice: string;
  trendPrediction: string;
  sentimentScore: number;
  sentimentLabel?: SentimentLabel;
}

/** 策略點位區 */
export interface ReportStrategy {
  idealBuy?: string;
  secondaryBuy?: string;
  stopLoss?: string;
  takeProfit?: string;
}

/** 詳情區（可摺疊） */
export interface ReportDetails {
  newsContent?: string;
  rawResult?: Record<string, unknown>;
  contextSnapshot?: Record<string, unknown>;
}

/** 完整分析報告 */
export interface AnalysisReport {
  meta: ReportMeta;
  summary: ReportSummary;
  strategy?: ReportStrategy;
  details?: ReportDetails;
}

// ============ 分析結果類型 ============

/** 同步分析返回結果 */
export interface AnalysisResult {
  queryId: string;
  stockCode: string;
  stockName: string;
  report: AnalysisReport;
  createdAt: string;
}

/** 非同步任務接受回應 */
export interface TaskAccepted {
  taskId: string;
  status: 'pending' | 'processing';
  message?: string;
}

/** 任務狀態 */
export interface TaskStatus {
  taskId: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress?: number;
  result?: AnalysisResult;
  error?: string;
}

/** 任務詳情（用於任務列表和 SSE 事件） */
export interface TaskInfo {
  taskId: string;
  stockCode: string;
  stockName?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  message?: string;
  reportType: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  error?: string;
}

/** 任務列表回應 */
export interface TaskListResponse {
  total: number;
  pending: number;
  processing: number;
  tasks: TaskInfo[];
}

/** 重複任務錯誤回應 */
export interface DuplicateTaskError {
  error: 'duplicate_task';
  message: string;
  stockCode: string;
  existingTaskId: string;
}

// ============ 歷史記錄類型 ============

/** 歷史記錄摘要（列表展示用） */
export interface HistoryItem {
  queryId: string;
  stockCode: string;
  stockName?: string;
  reportType?: string;
  sentimentScore?: number;
  operationAdvice?: string;
  createdAt: string;
}

/** 歷史記錄列表回應 */
export interface HistoryListResponse {
  total: number;
  page: number;
  limit: number;
  items: HistoryItem[];
}

/** 新聞情報條目 */
export interface NewsIntelItem {
  title: string;
  snippet: string;
  url: string;
}

/** 新聞情報回應 */
export interface NewsIntelResponse {
  total: number;
  items: NewsIntelItem[];
}

/** 歷史列表篩選參數 */
export interface HistoryFilters {
  stockCode?: string;
  startDate?: string;
  endDate?: string;
}

/** 歷史列表分頁參數 */
export interface HistoryPagination {
  page: number;
  limit: number;
}

// ============ 錯誤類型 ============

export interface ApiError {
  error: string;
  message: string;
  detail?: Record<string, unknown>;
}

// ============ 輔助函式 ============

/** 根據情緒評分取得情緒標籤 */
export const getSentimentLabel = (score: number): SentimentLabel => {
  if (score <= 20) return '極度悲觀';
  if (score <= 40) return '悲觀';
  if (score <= 60) return '中性';
  if (score <= 80) return '樂觀';
  return '極度樂觀';
};

/** 根據情緒評分取得顏色 */
export const getSentimentColor = (score: number): string => {
  if (score <= 20) return '#ef4444'; // red-500
  if (score <= 40) return '#f97316'; // orange-500
  if (score <= 60) return '#eab308'; // yellow-500
  if (score <= 80) return '#22c55e'; // green-500
  return '#10b981'; // emerald-500
};
