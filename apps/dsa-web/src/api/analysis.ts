import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  AnalysisRequest,
  AnalysisResult,
  AnalysisReport,
  TaskStatus,
  TaskListResponse,
} from '../types/analysis';

// ============ API 介面 ============

export const analysisApi = {
  /**
   * 觸發股票分析
   * @param data 分析請求參數
   * @returns 同步模式返回 AnalysisResult，異步模式返回 TaskAccepted（需檢查 status code）
   */
  analyze: async (data: AnalysisRequest): Promise<AnalysisResult> => {
    const requestData = {
      stock_code: data.stockCode,
      report_type: data.reportType || 'detailed',
      force_refresh: data.forceRefresh || false,
      async_mode: data.asyncMode || false,
    };

    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/analysis/analyze',
      requestData
    );

    const result = toCamelCase<AnalysisResult>(response.data);

    // 確保 report 欄位正確轉換
    if (result.report) {
      result.report = toCamelCase<AnalysisReport>(result.report);
    }

    return result;
  },

  /**
   * 異步模式觸發分析
   * 返回 task_id，透過 SSE 或輪詢獲取結果
   * @param data 分析請求參數
   * @returns 任務接受回應或拋出 409 錯誤
   */
  analyzeAsync: async (data: AnalysisRequest): Promise<{ taskId: string; status: string; message?: string }> => {
    const requestData = {
      stock_code: data.stockCode,
      report_type: data.reportType || 'detailed',
      force_refresh: data.forceRefresh || false,
      async_mode: true,
    };

    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/analysis/analyze',
      requestData,
      {
        // 允許 202 狀態碼
        validateStatus: (status) => status === 200 || status === 202 || status === 409,
      }
    );

    // 處理 409 重複提交錯誤
    if (response.status === 409) {
      const errorData = toCamelCase<{
        error: string;
        message: string;
        stockCode: string;
        existingTaskId: string;
      }>(response.data);
      throw new DuplicateTaskError(errorData.stockCode, errorData.existingTaskId, errorData.message);
    }

    return toCamelCase<{ taskId: string; status: string; message?: string }>(response.data);
  },

  /**
   * 獲取異步任務狀態
   * @param taskId 任務 ID
   */
  getStatus: async (taskId: string): Promise<TaskStatus> => {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/analysis/status/${taskId}`
    );

    const data = toCamelCase<TaskStatus>(response.data);

    // 確保巢狀的 result 也被正確轉換
    if (data.result) {
      data.result = toCamelCase<AnalysisResult>(data.result);
      if (data.result.report) {
        data.result.report = toCamelCase<AnalysisReport>(data.result.report);
      }
    }

    return data;
  },

  /**
   * 獲取任務列表
   * @param params 篩選參數
   */
  getTasks: async (params?: {
    status?: string;
    limit?: number;
  }): Promise<TaskListResponse> => {
    const response = await apiClient.get<Record<string, unknown>>(
      '/api/v1/analysis/tasks',
      { params }
    );

    const data = toCamelCase<TaskListResponse>(response.data);

    return data;
  },

  /**
   * 獲取 SSE 串流 URL
   * 用於 EventSource 連接
   */
  getTaskStreamUrl: (): string => {
    // 獲取 API base URL
    const baseUrl = apiClient.defaults.baseURL || '';
    return `${baseUrl}/api/v1/analysis/tasks/stream`;
  },
};

// ============ 自定義錯誤類別 ============

/**
 * 重複任務錯誤
 * 當股票正在分析中時拋出
 */
export class DuplicateTaskError extends Error {
  stockCode: string;
  existingTaskId: string;

  constructor(stockCode: string, existingTaskId: string, message?: string) {
    super(message || `股票 ${stockCode} 正在分析中`);
    this.name = 'DuplicateTaskError';
    this.stockCode = stockCode;
    this.existingTaskId = existingTaskId;
  }
}
