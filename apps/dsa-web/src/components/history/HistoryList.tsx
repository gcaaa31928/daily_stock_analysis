import type React from 'react';
import { useRef, useCallback, useEffect } from 'react';
import type { HistoryItem } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { formatDateTime } from '../../utils/format';

interface HistoryListProps {
  items: HistoryItem[];
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  selectedQueryId?: string;
  onItemClick: (queryId: string) => void;
  onLoadMore: () => void;
  className?: string;
}

/**
 * 歷史紀錄列表組件
 * 顯示最近的股票分析歷史，支持點擊查看詳情和滾動載入更多
 */
export const HistoryList: React.FC<HistoryListProps> = ({
  items,
  isLoading,
  isLoadingMore,
  hasMore,
  selectedQueryId,
  onItemClick,
  onLoadMore,
  className = '',
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const loadMoreTriggerRef = useRef<HTMLDivElement>(null);

  // 使用 IntersectionObserver 檢測滾動到底部
  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const target = entries[0];
      // 只有當觸發器真正可見且有更多數據時才載入
      if (target.isIntersecting && hasMore && !isLoading && !isLoadingMore) {
        // 確保容器有滾動能力（內容超過容器高度）
        const container = scrollContainerRef.current;
        if (container && container.scrollHeight > container.clientHeight) {
          onLoadMore();
        }
      }
    },
    [hasMore, isLoading, isLoadingMore, onLoadMore]
  );

  useEffect(() => {
    const trigger = loadMoreTriggerRef.current;
    const container = scrollContainerRef.current;
    if (!trigger || !container) return;

    const observer = new IntersectionObserver(handleObserver, {
      root: container,
      rootMargin: '20px', // 減小預載入距離
      threshold: 0.1, // 觸發器至少 10% 可見時才觸發
    });

    observer.observe(trigger);

    return () => {
      observer.disconnect();
    };
  }, [handleObserver]);

  return (
    <aside className={`glass-card overflow-hidden flex flex-col ${className}`}>
      <div ref={scrollContainerRef} className="p-3 flex-1 overflow-y-auto">
        <h2 className="text-xs font-medium text-purple uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          歷史紀錄
        </h2>

        {isLoading ? (
          <div className="flex justify-center py-6">
            <div className="w-5 h-5 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-6 text-muted text-xs">
            暫無歷史紀錄
          </div>
        ) : (
          <div className="space-y-1.5">
            {items.map((item) => (
              <button
                key={item.queryId}
                type="button"
                onClick={() => onItemClick(item.queryId)}
                className={`history-item w-full text-left ${selectedQueryId === item.queryId ? 'active' : ''
                  }`}
              >
                <div className="flex items-center gap-2 w-full">
                  {/* 情感分數指示條 */}
                  {item.sentimentScore !== undefined && (
                    <span
                      className="w-0.5 h-8 rounded-full flex-shrink-0"
                      style={{
                        backgroundColor: getSentimentColor(item.sentimentScore),
                        boxShadow: `0 0 6px ${getSentimentColor(item.sentimentScore)}40`
                      }}
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="font-medium text-white truncate text-xs">
                        {item.stockName || item.stockCode}
                      </span>
                      {item.sentimentScore !== undefined && (
                        <span
                          className="text-xs font-mono font-semibold px-1 py-0.5 rounded"
                          style={{
                            color: getSentimentColor(item.sentimentScore),
                            backgroundColor: `${getSentimentColor(item.sentimentScore)}15`
                          }}
                        >
                          {item.sentimentScore}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-xs text-muted font-mono">
                        {item.stockCode}
                      </span>
                      <span className="text-xs text-muted/50">·</span>
                      <span className="text-xs text-muted">
                        {formatDateTime(item.createdAt)}
                      </span>
                    </div>
                  </div>
                </div>
              </button>
            ))}

            {/* 載入更多觸發器 */}
            <div ref={loadMoreTriggerRef} className="h-4" />

            {/* 載入更多狀態 */}
            {isLoadingMore && (
              <div className="flex justify-center py-3">
                <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
              </div>
            )}

            {/* 沒有更多數據提示 */}
            {!hasMore && items.length > 0 && (
              <div className="text-center py-2 text-muted/50 text-xs">
                已載入全部
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
