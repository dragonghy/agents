import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getCompany,
  getUsage,
  getBilling,
  formatTokens,
  type Company,
  type User,
  type UsageSummary,
} from "../lib/api";
import Navbar from "../components/Navbar";

interface Props {
  user: User;
}

/** Simple SVG bar chart (no external library needed). */
function BarChart({ data }: { data: Array<{ date: string; total_tokens: number }> }) {
  if (!data.length) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-gray-400">
        <svg className="w-12 h-12 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
        <p className="text-sm">No usage data yet</p>
        <p className="text-xs mt-1">Usage will appear once agents start working</p>
      </div>
    );
  }

  const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
  const max = Math.max(...sorted.map((d) => d.total_tokens), 1);

  return (
    <div className="flex items-end gap-1 h-40">
      {sorted.map((d) => {
        const h = (d.total_tokens / max) * 100;
        return (
          <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
            <div
              className="w-full bg-indigo-500 rounded-t"
              style={{ height: `${Math.max(h, 2)}%` }}
              title={`${d.date}: ${formatTokens(d.total_tokens)} tokens`}
            />
            <span className="text-[10px] text-gray-400 rotate-[-45deg] origin-top-left whitespace-nowrap">
              {d.date.slice(5)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function CompanyUsage({ user }: Props) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [company, setCompany] = useState<Company | null>(null);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [plan, setPlan] = useState<{ name: string; price_monthly: number; features: string[] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      getCompany(id),
      getUsage(id, undefined, new Date().toISOString().slice(0, 10)),
      getBilling(id),
    ])
      .then(([c, u, b]) => {
        setCompany(c);
        setSummary(u.summary);
        setPlan(b.plan);
      })
      .catch(() => navigate("/dashboard"))
      .finally(() => setLoading(false));
  }, [id, navigate]);

  if (loading || !company) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Navbar user={user} />
        <div className="text-center text-gray-500 py-16">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar user={user} />

      <main className="max-w-3xl mx-auto px-6 py-8">
        <div className="flex items-center gap-4 mb-6">
          <button
            onClick={() => navigate(`/companies/${id}/settings`)}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            &larr; Settings
          </button>
          <h1 className="text-2xl font-bold text-gray-900">
            {company.name} — Usage & Billing
          </h1>
        </div>

        {/* Plan info */}
        {plan && (
          <section className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
            <h2 className="font-semibold text-lg mb-3">Current Plan</h2>
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xl font-bold text-indigo-600">{plan.name}</span>
                <span className="text-gray-500 ml-2">
                  {plan.price_monthly === 0 ? "Free" : `$${plan.price_monthly}/mo`}
                </span>
              </div>
              <button
                disabled
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-400 cursor-not-allowed"
              >
                Upgrade (Coming soon)
              </button>
            </div>
            <ul className="mt-3 space-y-1">
              {plan.features.map((f, i) => (
                <li key={i} className="text-sm text-gray-600">&#10003; {f}</li>
              ))}
            </ul>
          </section>
        )}

        {/* Usage summary */}
        <section className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
          <h2 className="font-semibold text-lg mb-4">Token Usage</h2>
          {summary ? (
            <>
              <div className="grid grid-cols-3 gap-4 mb-6">
                <div className="text-center p-4 bg-gray-50 rounded-lg">
                  <div className="text-2xl font-bold text-indigo-600">
                    {formatTokens(summary.total_tokens)}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">Total Tokens</div>
                </div>
                <div className="text-center p-4 bg-gray-50 rounded-lg">
                  <div className="text-2xl font-bold text-blue-600">
                    {formatTokens(summary.total_input)}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">Input</div>
                </div>
                <div className="text-center p-4 bg-gray-50 rounded-lg">
                  <div className="text-2xl font-bold text-green-600">
                    {formatTokens(summary.total_output)}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">Output</div>
                </div>
              </div>

              {/* Daily chart */}
              <h3 className="text-sm font-medium text-gray-700 mb-2">Daily Usage (Last 30 days)</h3>
              <div className="bg-gray-50 p-4 rounded-lg mb-6">
                <BarChart data={summary.daily} />
              </div>

              {/* By model */}
              {summary.by_model.length > 0 && (
                <>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">By Model</h3>
                  <div className="space-y-2">
                    {summary.by_model.map((m) => (
                      <div
                        key={m.model}
                        className="flex items-center justify-between bg-gray-50 p-3 rounded-lg"
                      >
                        <span className="text-sm font-mono">{m.model}</span>
                        <span className="text-sm text-gray-600">
                          {formatTokens(m.total_tokens)} tokens
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          ) : (
            <p className="text-gray-400">No usage data available.</p>
          )}
        </section>
      </main>
    </div>
  );
}
