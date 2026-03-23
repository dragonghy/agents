import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getCompany,
  updateCompany,
  updateAuth,
  deleteCompany,
  stopInstance,
  pauseInstance,
  resumeInstance,
  type Company,
  type User,
} from "../lib/api";
import Navbar from "../components/Navbar";

interface Props {
  user: User;
}

export default function CompanySettings({ user }: Props) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [company, setCompany] = useState<Company | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  // Edit fields
  const [name, setName] = useState("");
  const [authType, setAuthType] = useState("");
  const [authToken, setAuthToken] = useState("");

  useEffect(() => {
    if (!id) return;
    getCompany(id)
      .then((c) => {
        setCompany(c);
        setName(c.name);
        setAuthType(c.auth_type || "oauth_token");
      })
      .catch(() => navigate("/dashboard"))
      .finally(() => setLoading(false));
  }, [id, navigate]);

  const handleSaveName = async () => {
    if (!id || !name) return;
    setSaving(true);
    try {
      const updated = await updateCompany(id, { name });
      setCompany(updated);
      setMessage("Name updated");
    } catch {
      setMessage("Failed to update name");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAuth = async () => {
    if (!id || !authToken) return;
    setSaving(true);
    try {
      const updated = await updateAuth(id, authType, authToken);
      setCompany(updated);
      setAuthToken("");
      setMessage("Authentication updated");
    } catch {
      setMessage("Failed to update authentication");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!id || !company) return;
    if (!confirm(`Delete "${company.name}"? This action cannot be undone.`)) return;
    try {
      await deleteCompany(id);
      navigate("/dashboard");
    } catch {
      setMessage("Failed to delete");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <Navbar user={user} />
        <div className="text-center text-gray-500 py-16">Loading...</div>
      </div>
    );
  }

  if (!company) return null;

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar user={user} />

      <main className="max-w-2xl mx-auto px-6 py-8">
        <button
          onClick={() => navigate("/dashboard")}
          className="text-sm text-gray-500 hover:text-gray-700 mb-4 inline-block"
        >
          &larr; Back to Dashboard
        </button>

        <h1 className="text-2xl font-bold text-gray-900 mb-6">
          {company.name} — Settings
        </h1>

        {message && (
          <div className="mb-4 p-3 bg-blue-50 text-blue-700 rounded-lg text-sm">
            {message}
          </div>
        )}

        {/* Quick links */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={() => navigate(`/companies/${id}/usage`)}
            className="px-4 py-2 bg-indigo-50 text-indigo-700 rounded-lg hover:bg-indigo-100 text-sm font-medium"
          >
            Usage & Billing
          </button>
        </div>

        {/* General */}
        <section className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
          <h2 className="font-semibold text-lg mb-4">General</h2>
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
              />
              <button
                onClick={handleSaveName}
                disabled={saving || name === company.name}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Slug</label>
            <p className="text-gray-600">{company.slug}</p>
          </div>
          <div className="mt-3">
            <label className="block text-sm font-medium text-gray-700 mb-1">Template</label>
            <p className="text-gray-600 capitalize">{company.template}</p>
          </div>
          <div className="mt-3">
            <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
            <p className={`capitalize ${company.status === 'error' ? 'text-red-600 font-medium' : 'text-gray-600'}`}>
              {company.status}
            </p>
          </div>
          {(company.url || company.port) && company.status === 'running' && (
            <div className="mt-3">
              <label className="block text-sm font-medium text-gray-700 mb-1">Instance URL</label>
              <a
                href={company.url || `http://localhost:${company.port}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-600 hover:text-indigo-700 underline text-sm font-mono"
              >
                {company.url || `http://localhost:${company.port}`}
              </a>
            </div>
          )}
        </section>

        {/* Authentication */}
        <section className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-6">
          <h2 className="font-semibold text-lg mb-4">Authentication</h2>
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
            <select
              value={authType}
              onChange={(e) => setAuthType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
            >
              <option value="oauth_token">OAuth Token</option>
              <option value="api_key">API Key</option>
              <option value="bedrock">AWS Bedrock</option>
              <option value="vertex">Google Vertex</option>
            </select>
          </div>
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              New Token / Key
            </label>
            <div className="flex gap-2">
              <input
                type="password"
                value={authToken}
                onChange={(e) => setAuthToken(e.target.value)}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none font-mono text-sm"
                placeholder="Paste new token to update"
              />
              <button
                onClick={handleSaveAuth}
                disabled={saving || !authToken}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm disabled:opacity-50"
              >
                Update
              </button>
            </div>
          </div>
          <p className="text-xs text-gray-400">
            Current: {company.auth_type || "Not configured"}
          </p>
        </section>

        {/* Danger Zone */}
        <section className="bg-white p-6 rounded-xl border border-red-200 mb-6">
          <h2 className="font-semibold text-lg text-red-600 mb-4">Danger Zone</h2>
          <div className="flex flex-wrap gap-3">
            {company.status === "running" && (
              <button
                onClick={async () => {
                  await pauseInstance(company.id);
                  const c = await getCompany(company.id);
                  setCompany(c);
                }}
                className="px-4 py-2 border border-yellow-400 text-yellow-700 rounded-lg hover:bg-yellow-50 text-sm"
              >
                Pause Instance
              </button>
            )}
            {company.status === "paused" && (
              <button
                onClick={async () => {
                  await resumeInstance(company.id);
                  const c = await getCompany(company.id);
                  setCompany(c);
                }}
                className="px-4 py-2 border border-green-400 text-green-700 rounded-lg hover:bg-green-50 text-sm"
              >
                Resume Instance
              </button>
            )}
            {(company.status === "running" || company.status === "paused") && (
              <button
                onClick={async () => {
                  await stopInstance(company.id);
                  const c = await getCompany(company.id);
                  setCompany(c);
                }}
                className="px-4 py-2 border border-gray-400 text-gray-700 rounded-lg hover:bg-gray-50 text-sm"
              >
                Stop Instance
              </button>
            )}
            <button
              onClick={handleDelete}
              className="px-4 py-2 border border-red-400 text-red-600 rounded-lg hover:bg-red-50 text-sm"
            >
              Delete Company
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}
