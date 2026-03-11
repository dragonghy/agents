import { useEffect, useState, useRef } from 'react';
import { fetchMessages, fetchConversation } from '../api/messages';
import { fetchAgents } from '../api/agents';
import type { ConversationThread, Message } from '../types/message';
import type { Agent } from '../types/agent';

function formatTime(dateStr: string): string {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'Z');
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

export default function Messages() {
  const [threads, setThreads] = useState<ConversationThread[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedThread, setSelectedThread] = useState<{ a: string; b: string } | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msgInput, setMsgInput] = useState('');
  const [sender, setSender] = useState('human');
  const [recipient, setRecipient] = useState('');
  const [sending, setSending] = useState(false);
  const [agentsOnly, setAgentsOnly] = useState(true);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const params: Record<string, string> = {};
        if (agentsOnly) params.agents_only = 'true';
        const data = await fetchMessages(params);
        if (active) {
          setThreads(data.threads);
          setError(null);
          if (data.threads.length > 0 && !selectedThread) {
            setSelectedThread({ a: data.threads[0].agent_a, b: data.threads[0].agent_b });
          }
        }
      } catch (e) {
        if (active) setError(String(e));
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 10000);
    return () => { active = false; clearInterval(interval); };
  }, [agentsOnly]);

  useEffect(() => {
    if (!selectedThread) return;
    let active = true;
    async function load() {
      try {
        const data = await fetchConversation(selectedThread!.a, selectedThread!.b, { limit: '100' });
        if (active) {
          setMessages([...data].reverse());
          setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
        }
      } catch (e) {
        if (active) setError(String(e));
      }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => { active = false; clearInterval(interval); };
  }, [selectedThread?.a, selectedThread?.b]);

  async function handleSend() {
    const to = selectedThread
      ? (sender === selectedThread.a ? selectedThread.b : selectedThread.a)
      : recipient;
    if (!msgInput.trim() || !to) return;
    setSending(true);
    try {
      await fetch('/api/v1/messages/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_agent: sender, to_agent: to, message: msgInput }),
      });
      setMsgInput('');
      if (selectedThread) {
        const data = await fetchConversation(selectedThread.a, selectedThread.b, { limit: '100' });
        setMessages([...data].reverse());
        setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
      }
      const threadParams: Record<string, string> = {};
      if (agentsOnly) threadParams.agents_only = 'true';
      const threadData = await fetchMessages(threadParams);
      setThreads(threadData.threads);
    } catch (e) {
      setError(String(e));
    } finally {
      setSending(false);
    }
  }

  function handleNewConversation() {
    if (!recipient) return;
    const a = sender < recipient ? sender : recipient;
    const b = sender < recipient ? recipient : sender;
    setSelectedThread({ a, b });
  }

  if (loading) {
    return (
      <div>
        <Skeleton className="h-8 w-32 mb-4" />
        <Skeleton className="h-10 w-full mb-4" />
        <div className="flex gap-4" style={{ height: '400px' }}>
          <Skeleton className="w-72 h-full" />
          <Skeleton className="flex-1 h-full" />
        </div>
      </div>
    );
  }

  if (error) return <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">Error: {error}</div>;

  const senderOptions = ['human', ...agents.map((a) => a.id)];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Messages</h2>
        <button
          onClick={() => setAgentsOnly(!agentsOnly)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
            agentsOnly
              ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
              : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
          }`}
          title={agentsOnly ? 'Showing current agents only. Click to show all conversations.' : 'Showing all conversations. Click to filter to current agents only.'}
        >
          <span className={`inline-block w-8 h-4 rounded-full relative transition-colors ${
            agentsOnly ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'
          }`}>
            <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${
              agentsOnly ? 'translate-x-4' : 'translate-x-0.5'
            }`} />
          </span>
          {agentsOnly ? 'Current agents' : 'All conversations'}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4 items-center text-sm">
        <label className="text-gray-600 dark:text-gray-400">Send as:</label>
        <select value={sender} onChange={(e) => setSender(e.target.value)}
          className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200">
          {senderOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label className="text-gray-600 dark:text-gray-400 ml-2">New conversation with:</label>
        <select value={recipient} onChange={(e) => setRecipient(e.target.value)}
          className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200">
          <option value="">Select agent...</option>
          {agents.map((a) => <option key={a.id} value={a.id}>{a.id}</option>)}
        </select>
        <button onClick={handleNewConversation} disabled={!recipient}
          className="px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50">
          Start
        </button>
      </div>

      <div className="flex gap-4" style={{ height: 'calc(100vh - 250px)' }}>
        {/* Thread list */}
        <div className="w-72 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 overflow-auto flex-shrink-0 hidden sm:block">
          {threads.length === 0 ? (
            <div className="p-4 text-gray-400 dark:text-gray-500 text-sm">No conversations yet</div>
          ) : (
            threads.map((thread) => {
              const isSelected = selectedThread?.a === thread.agent_a && selectedThread?.b === thread.agent_b;
              return (
                <button
                  key={`${thread.agent_a}-${thread.agent_b}`}
                  onClick={() => setSelectedThread({ a: thread.agent_a, b: thread.agent_b })}
                  className={`w-full text-left px-4 py-3 border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 ${
                    isSelected ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-l-blue-500' : ''
                  }`}
                >
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-medium text-sm text-gray-900 dark:text-gray-100">
                      {thread.agent_a} &harr; {thread.agent_b}
                    </span>
                    <span className="text-xs text-gray-400 dark:text-gray-500">{thread.message_count}</span>
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
                    <span className="font-medium">{thread.last_sender}:</span>{' '}
                    {thread.last_message}
                  </div>
                  <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                    {formatTime(thread.last_message_at)}
                  </div>
                </button>
              );
            })
          )}
        </div>

        {/* Conversation view */}
        <div className="flex-1 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 flex flex-col min-w-0">
          {!selectedThread ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-500">
              Select a conversation or start a new one
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
                <span className="font-medium text-gray-800 dark:text-gray-100">
                  {selectedThread.a} &harr; {selectedThread.b}
                </span>
              </div>
              <div className="flex-1 overflow-auto p-4 space-y-3">
                {messages.map((msg) => {
                  const isLeft = msg.from_agent === selectedThread.a;
                  return (
                    <div key={msg.id} className={`flex ${isLeft ? 'justify-start' : 'justify-end'}`}>
                      <div className="max-w-[70%]">
                        <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                          {msg.from_agent} &middot; {formatTime(msg.created_at)}
                        </div>
                        <div
                          className={`px-3 py-2 rounded-lg text-sm whitespace-pre-wrap ${
                            isLeft
                              ? 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 rounded-tl-none'
                              : 'bg-blue-500 text-white rounded-tr-none'
                          }`}
                        >
                          {msg.body}
                        </div>
                      </div>
                    </div>
                  );
                })}
                {messages.length === 0 && (
                  <div className="text-center text-gray-400 dark:text-gray-500 text-sm py-8">No messages in this conversation</div>
                )}
                <div ref={chatEndRef} />
              </div>
              <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 flex gap-2">
                <input
                  type="text"
                  value={msgInput}
                  onChange={(e) => setMsgInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                  placeholder={`Send as ${sender}...`}
                  className="flex-1 border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-400 dark:placeholder-gray-500"
                />
                <button
                  onClick={handleSend}
                  disabled={!msgInput.trim() || sending}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {sending ? '...' : 'Send'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
