import { useEffect, useRef, useCallback } from 'react';
import { analysisApi } from '../api/analysis';
import type { TaskInfo } from '../types/analysis';

/**
 * SSE 事件類型
 */
export type SSEEventType =
  | 'connected'
  | 'task_created'
  | 'task_started'
  | 'task_completed'
  | 'task_failed'
  | 'heartbeat';

/**
 * SSE 事件資料
 */
export interface SSEEvent {
  type: SSEEventType;
  task?: TaskInfo;
  timestamp?: string;
}

/**
 * SSE Hook 設定
 */
export interface UseTaskStreamOptions {
  /** 任務建立回呼 */
  onTaskCreated?: (task: TaskInfo) => void;
  /** 任務開始回呼 */
  onTaskStarted?: (task: TaskInfo) => void;
  /** 任務完成回呼 */
  onTaskCompleted?: (task: TaskInfo) => void;
  /** 任務失敗回呼 */
  onTaskFailed?: (task: TaskInfo) => void;
  /** 連接成功回呼 */
  onConnected?: () => void;
  /** 連接錯誤回呼 */
  onError?: (error: Event) => void;
  /** 是否自動重連 */
  autoReconnect?: boolean;
  /** 重連延遲(ms) */
  reconnectDelay?: number;
  /** 是否啟用 */
  enabled?: boolean;
}

/**
 * SSE Hook 回傳值
 */
export interface UseTaskStreamResult {
  /** 是否已連接 */
  isConnected: boolean;
  /** 手動重連 */
  reconnect: () => void;
  /** 手動斷開 */
  disconnect: () => void;
}

/**
 * 任務流 SSE Hook
 * 用於接收即時任務狀態更新
 *
 * @example
 * ```tsx
 * const { isConnected } = useTaskStream({
 *   onTaskCompleted: (task) => {
 *     console.log('Task completed:', task);
 *     refreshHistory();
 *   },
 *   onTaskFailed: (task) => {
 *     showError(task.error);
 *   },
 * });
 * ```
 */
export function useTaskStream(options: UseTaskStreamOptions = {}): UseTaskStreamResult {
  const {
    onTaskCreated,
    onTaskStarted,
    onTaskCompleted,
    onTaskFailed,
    onConnected,
    onError,
    autoReconnect = true,
    reconnectDelay = 3000,
    enabled = true,
  } = options;

  const eventSourceRef = useRef<EventSource | null>(null);
  const isConnectedRef = useRef(false);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 使用 ref 儲存回呼，避免 SSE 連接因回呼變化而頻繁重連
  const callbacksRef = useRef({
    onTaskCreated,
    onTaskStarted,
    onTaskCompleted,
    onTaskFailed,
    onConnected,
    onError,
  });

  // 每次渲染時更新回呼 ref（確保事件處理使用最新回呼）
  useEffect(() => {
    callbacksRef.current = {
      onTaskCreated,
      onTaskStarted,
      onTaskCompleted,
      onTaskFailed,
      onConnected,
      onError,
    };
  });

  // 將 snake_case 轉換為 camelCase
  const toCamelCase = (data: Record<string, unknown>): TaskInfo => {
    return {
      taskId: data.task_id as string,
      stockCode: data.stock_code as string,
      stockName: data.stock_name as string | undefined,
      status: data.status as TaskInfo['status'],
      progress: data.progress as number,
      message: data.message as string | undefined,
      reportType: data.report_type as string,
      createdAt: data.created_at as string,
      startedAt: data.started_at as string | undefined,
      completedAt: data.completed_at as string | undefined,
      error: data.error as string | undefined,
    };
  };

  // 解析 SSE 資料
  const parseEventData = useCallback((eventData: string): TaskInfo | null => {
    try {
      const data = JSON.parse(eventData);
      return toCamelCase(data);
    } catch (e) {
      console.error('Failed to parse SSE event data:', e);
      return null;
    }
  }, []);

  // 建立 EventSource 連接
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const url = analysisApi.getTaskStreamUrl();
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    // 連接成功
    eventSource.addEventListener('connected', () => {
      isConnectedRef.current = true;
      callbacksRef.current.onConnected?.();
    });

    // 任務建立
    eventSource.addEventListener('task_created', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskCreated?.(task);
    });

    // 任務開始
    eventSource.addEventListener('task_started', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskStarted?.(task);
    });

    // 任務完成
    eventSource.addEventListener('task_completed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskCompleted?.(task);
    });

    // 任務失敗
    eventSource.addEventListener('task_failed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskFailed?.(task);
    });

    // 心跳 - 僅用於保持連接
    eventSource.addEventListener('heartbeat', () => {
      // 可選：更新最後心跳時間
    });

    // 錯誤處理
    eventSource.onerror = (error) => {
      isConnectedRef.current = false;
      callbacksRef.current.onError?.(error);

      // 自動重連
      if (autoReconnect && enabled) {
        eventSource.close();
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, reconnectDelay);
      }
    };
  }, [
    autoReconnect,
    reconnectDelay,
    enabled,
    parseEventData,
  ]);

  // 斷開連接
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    isConnectedRef.current = false;
  }, []);

  // 重連
  const reconnect = useCallback(() => {
    disconnect();
    connect();
  }, [disconnect, connect]);

  // 啟用/停用時連接/斷開
  useEffect(() => {
    if (enabled) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      disconnect();
    };
  }, [enabled, connect, disconnect]);

  return {
    isConnected: isConnectedRef.current,
    reconnect,
    disconnect,
  };
}

export default useTaskStream;
