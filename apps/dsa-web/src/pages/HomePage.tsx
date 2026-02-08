import type React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { HistoryItem, AnalysisReport, TaskInfo } from '../types/analysis';
import { historyApi } from '../api/history';
import { analysisApi, DuplicateTaskError } from '../api/analysis';
import { validateStockCode } from '../utils/validation';
import { getRecentStartDate, toDateInputValue } from '../utils/format';
import { useAnalysisStore } from '../stores/analysisStore';
import { ReportSummary } from '../components/report';
import { HistoryList } from '../components/history';
import { TaskPanel } from '../components/tasks';
import { useTaskStream } from '../hooks';

/**
 * 首頁 - 單頁設計
 * 頂部輸入 + 左側歷史 + 右側報告
 */
const HomePage: React.FC = () => {
  const { setLoading, setError: setStoreError } = useAnalysisStore();

  // 輸入狀態
  const [stockCode, setStockCode] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [inputError, setInputError] = useState<string>();

// 歷史列表狀態
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 20;

  // 報告詳情狀態
  const [selectedReport, setSelectedReport] = useState<AnalysisReport | null>(null);
  const [isLoadingReport, setIsLoadingReport] = useState(false);

  // 任務佇列狀態
  const [activeTasks, setActiveTasks] = useState<TaskInfo[]>([]);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);

  // 用於追蹤當前分析請求，避免競態條件
  const analysisRequestIdRef = useRef<number>(0);

  // 更新任務列表中的任務
  const updateTask = useCallback((updatedTask: TaskInfo) => {
    setActiveTasks((prev) => {
      const index = prev.findIndex((t) => t.taskId === updatedTask.taskId);
      if (index >= 0) {
        const newTasks = [...prev];
        newTasks[index] = updatedTask;
        return newTasks;
      }
      return prev;
    });
  }, []);

  // 移除已完成/失敗的任務
  const removeTask = useCallback((taskId: string) => {
    setActiveTasks((prev) => prev.filter((t) => t.taskId !== taskId));
  }, []);

  // SSE 任務流
  useTaskStream({
    onTaskCreated: (task) => {
      setActiveTasks((prev) => {
        // 避免重複添加
        if (prev.some((t) => t.taskId === task.taskId)) return prev;
        return [...prev, task];
      });
    },
    onTaskStarted: updateTask,
    onTaskCompleted: (task) => {
      // 重新整理歷史列表
      fetchHistory();
      // 延遲移除任務，讓使用者看到完成狀態
      setTimeout(() => removeTask(task.taskId), 2000);
    },
    onTaskFailed: (task) => {
      updateTask(task);
      // 顯示錯誤提示
      setStoreError(task.error || '分析失敗');
      // 延遲移除任務
      setTimeout(() => removeTask(task.taskId), 5000);
    },
    onError: () => {
      console.warn('SSE 連線中斷，正在重新連線...');
    },
    enabled: true,
  });

// 載入歷史列表
  const fetchHistory = useCallback(async (autoSelectFirst = false, reset = true) => {
    if (reset) {
      setIsLoadingHistory(true);
      setCurrentPage(1);
    } else {
      setIsLoadingMore(true);
    }

    const page = reset ? 1 : currentPage + 1;

    try {
      const response = await historyApi.getList({
        startDate: getRecentStartDate(30),
        endDate: toDateInputValue(new Date()),
        page,
        limit: pageSize,
      });

      if (reset) {
        setHistoryItems(response.items);
      } else {
        setHistoryItems(prev => [...prev, ...response.items]);
      }

      // 判斷是否還有更多資料
      const totalLoaded = reset ? response.items.length : historyItems.length + response.items.length;
      setHasMore(totalLoaded < response.total);
      setCurrentPage(page);

      // 如果需要自動選擇第一條，且有資料，且當前沒有選中報告
      if (autoSelectFirst && response.items.length > 0 && !selectedReport) {
        const firstItem = response.items[0];
        setIsLoadingReport(true);
        try {
          const report = await historyApi.getDetail(firstItem.queryId);
          setSelectedReport(report);
        } catch (err) {
          console.error('Failed to fetch first report:', err);
        } finally {
          setIsLoadingReport(false);
        }
      }
    } catch (err) {
      console.error('Failed to fetch history:', err);
    } finally {
      setIsLoadingHistory(false);
      setIsLoadingMore(false);
    }
  }, [selectedReport, currentPage, historyItems.length, pageSize]);

  // 載入更多歷史記錄
  const handleLoadMore = useCallback(() => {
    if (!isLoadingMore && hasMore) {
      fetchHistory(false, false);
    }
  }, [fetchHistory, isLoadingMore, hasMore]);

  // 初始載入 - 自動選擇第一條
  useEffect(() => {
    fetchHistory(true);
  }, []);

  // 點擊歷史項載入報告
  const handleHistoryClick = async (queryId: string) => {
    // 取消當前分析請求的結果顯示（透過遞增 requestId）
    analysisRequestIdRef.current += 1;

    setIsLoadingReport(true);
    try {
      const report = await historyApi.getDetail(queryId);
      setSelectedReport(report);
    } catch (err) {
      console.error('Failed to fetch report:', err);
    } finally {
      setIsLoadingReport(false);
    }
  };

  // 分析股票（非同步模式）
  const handleAnalyze = async () => {
    const { valid, message, normalized } = validateStockCode(stockCode);
    if (!valid) {
      setInputError(message);
      return;
    }

    setInputError(undefined);
    setDuplicateError(null);
    setIsAnalyzing(true);
    setLoading(true);
    setStoreError(null);

    // 記錄當前請求的 ID
    const currentRequestId = ++analysisRequestIdRef.current;

    try {
      // 使用非同步模式提交分析
      const response = await analysisApi.analyzeAsync({
        stockCode: normalized,
        reportType: 'detailed',
      });

      // 清空輸入框
      if (currentRequestId === analysisRequestIdRef.current) {
        setStockCode('');
      }

      // 任務已提交，SSE 會推送更新
      console.log('Task submitted:', response.taskId);
    } catch (err) {
      console.error('Analysis failed:', err);
      if (currentRequestId === analysisRequestIdRef.current) {
        if (err instanceof DuplicateTaskError) {
          // 顯示重複任務錯誤
          setDuplicateError(`股票 ${err.stockCode} 正在分析中，請等待完成`);
        } else {
          setStoreError(err instanceof Error ? err.message : '分析失敗');
        }
      }
    } finally {
      setIsAnalyzing(false);
      setLoading(false);
    }
  };

  // 按 Enter 提交
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && stockCode && !isAnalyzing) {
      handleAnalyze();
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* 頂部輸入列 */}
      <header className="flex-shrink-0 px-4 py-3 border-b border-white/5">
        <div className="flex items-center gap-2 max-w-2xl">
          <div className="flex-1 relative">
            <input
              type="text"
              value={stockCode}
              onChange={(e) => {
                setStockCode(e.target.value.toUpperCase());
                setInputError(undefined);
              }}
              onKeyDown={handleKeyDown}
              placeholder="輸入股票代碼，如 2330.TW、0700.HK、AAPL"
              disabled={isAnalyzing}
              className={`input-terminal w-full ${inputError ? 'border-danger/50' : ''}`}
            />
            {inputError && (
              <p className="absolute -bottom-4 left-0 text-xs text-danger">{inputError}</p>
            )}
            {duplicateError && (
              <p className="absolute -bottom-4 left-0 text-xs text-warning">{duplicateError}</p>
            )}
          </div>
          <button
            type="button"
            onClick={handleAnalyze}
            disabled={!stockCode || isAnalyzing}
            className="btn-primary flex items-center gap-1.5 whitespace-nowrap"
          >
            {isAnalyzing ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                分析中
              </>
            ) : (
              '分析'
            )}
          </button>
        </div>
      </header>

      {/* 主內容區 */}
      <main className="flex-1 flex overflow-hidden p-3 gap-3">
{/* 左側：任務面板 + 歷史列表 */}
        <div className="flex flex-col gap-3 w-64 flex-shrink-0 overflow-hidden">
          {/* 任務面板 */}
          <TaskPanel tasks={activeTasks} />

          {/* 歷史列表 */}
          <HistoryList
            items={historyItems}
            isLoading={isLoadingHistory}
            isLoadingMore={isLoadingMore}
            hasMore={hasMore}
            selectedQueryId={selectedReport?.meta.queryId}
            onItemClick={handleHistoryClick}
            onLoadMore={handleLoadMore}
            className="max-h-[62vh] overflow-hidden"
          />
        </div>

        {/* 右側報告詳情 */}
        <section className="flex-1 overflow-y-auto pl-1">
          {isLoadingReport ? (
            <div className="flex flex-col items-center justify-center h-full">
              <div className="w-10 h-10 border-3 border-cyan/20 border-t-cyan rounded-full animate-spin" />
              <p className="mt-3 text-secondary text-sm">載入報告中...</p>
            </div>
          ) : selectedReport ? (
            <div className="max-w-4xl">
              {/* 報告內容 */}
              <ReportSummary data={selectedReport} isHistory />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-12 h-12 mb-3 rounded-xl bg-elevated flex items-center justify-center">
                <svg className="w-6 h-6 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              <h3 className="text-base font-medium text-white mb-1.5">開始分析</h3>
              <p className="text-xs text-muted max-w-xs">
                輸入股票代碼進行分析，或從左側選擇歷史報告查看
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default HomePage;
