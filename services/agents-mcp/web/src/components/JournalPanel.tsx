import { useEffect, useState, useCallback } from 'react';
import Markdown from 'react-markdown';
import { fetchAgentJournals, fetchAgentJournal } from '../api/agents';
import type { JournalEntry } from '../api/agents';

const PAGE_SIZE = 7;

interface JournalItemProps {
  agentId: string;
  entry: JournalEntry;
  defaultOpen: boolean;
}

function JournalItem({ agentId, entry, defaultOpen }: JournalItemProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && content === null && !loading) {
      setLoading(true);
      fetchAgentJournal(agentId, entry.date)
        .then((data) => {
          setContent(data.content);
          setError(null);
        })
        .catch((e) => setError(String(e)))
        .finally(() => setLoading(false));
    }
  }, [open, agentId, entry.date, content, loading]);

  // Format date for display
  const dateLabel = (() => {
    try {
      const d = new Date(entry.date + 'T00:00:00');
      const weekday = d.toLocaleDateString('en-US', { weekday: 'short' });
      return `${entry.date} (${weekday})`;
    } catch {
      return entry.date;
    }
  })();

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      >
        <span className="font-medium text-sm text-gray-800 dark:text-gray-200">
          {dateLabel}
        </span>
        <svg
          className={`w-4 h-4 text-gray-500 dark:text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="px-4 py-3 bg-white dark:bg-gray-900">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading...
            </div>
          )}
          {error && (
            <p className="text-sm text-red-500 dark:text-red-400">{error}</p>
          )}
          {content !== null && (
            <div className="prose prose-sm dark:prose-invert max-w-none
              prose-headings:text-gray-800 dark:prose-headings:text-gray-100
              prose-h1:text-lg prose-h1:mt-0 prose-h1:mb-3
              prose-h2:text-base prose-h2:mt-4 prose-h2:mb-2
              prose-p:text-gray-700 dark:prose-p:text-gray-300
              prose-li:text-gray-700 dark:prose-li:text-gray-300
              prose-strong:text-gray-800 dark:prose-strong:text-gray-200
              prose-code:text-pink-600 dark:prose-code:text-pink-400
              prose-code:bg-gray-100 dark:prose-code:bg-gray-800
              prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs
              prose-pre:bg-gray-900 dark:prose-pre:bg-black
              prose-pre:text-gray-100 prose-pre:text-xs
              prose-a:text-blue-600 dark:prose-a:text-blue-400
              prose-table:text-sm
              prose-th:px-3 prose-th:py-1.5 prose-th:bg-gray-100 dark:prose-th:bg-gray-800
              prose-td:px-3 prose-td:py-1.5 prose-td:border-gray-200 dark:prose-td:border-gray-700"
            >
              <Markdown>{content}</Markdown>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function JournalPanel({ agentId }: { agentId: string }) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const loadJournals = useCallback(
    async (off: number, append = false) => {
      try {
        setLoading(true);
        const data = await fetchAgentJournals(agentId, PAGE_SIZE, off);
        setEntries((prev) => (append ? [...prev, ...data.journals] : data.journals));
        setTotal(data.total);
        setOffset(off);
        setError(null);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [agentId],
  );

  useEffect(() => {
    setEntries([]);
    setOffset(0);
    loadJournals(0);
  }, [agentId, loadJournals]);

  const hasMore = offset + PAGE_SIZE < total;

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800">
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100">
          Journal
          {total > 0 && (
            <span className="ml-2 text-xs font-normal text-gray-400">
              {total} {total === 1 ? 'entry' : 'entries'}
            </span>
          )}
        </h3>
      </div>

      <div className="p-4 space-y-2">
        {!loading && entries.length === 0 && !error && (
          <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-6">
            No journal entries yet
          </p>
        )}
        {error && !entries.length && (
          <p className="text-sm text-red-500 dark:text-red-400">{error}</p>
        )}

        {entries.map((entry, idx) => (
          <JournalItem
            key={entry.date}
            agentId={agentId}
            entry={entry}
            defaultOpen={idx === 0}
          />
        ))}

        {hasMore && (
          <button
            onClick={() => loadJournals(offset + PAGE_SIZE, true)}
            disabled={loading}
            className="w-full py-2 text-sm text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 disabled:opacity-50"
          >
            {loading ? 'Loading...' : `Load older entries (${total - entries.length} remaining)`}
          </button>
        )}

        {loading && entries.length === 0 && (
          <div className="flex items-center justify-center gap-2 text-sm text-gray-400 py-6">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Loading journals...
          </div>
        )}
      </div>
    </div>
  );
}
