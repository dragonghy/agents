import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  listCompanies,
  startInstance,
  stopInstance,
  deleteCompany,
  type Company,
  type User,
} from "../lib/api";
import Navbar from "../components/Navbar";

const STATUS_COLORS: Record<string, string> = {
  running: "bg-green-500",
  stopped: "bg-gray-400",
  paused: "bg-yellow-500",
  creating: "bg-blue-500",
  error: "bg-red-500",
};

const STATUS_LABELS: Record<string, string> = {
  running: "Running",
  stopped: "Stopped",
  paused: "Paused",
  creating: "Creating...",
  error: "Error",
};

interface Props {
  user: User;
}

export default function Dashboard({ user }: Props) {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const data = await listCompanies();
      setCompanies(data);
    } catch {
      // Ignore errors
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleAction = async (id: string, action: () => Promise<unknown>) => {
    setActionLoading(id);
    try {
      await action();
      await refresh();
    } catch {
      // Ignore
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar user={user} />

      <main className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Your Companies</h1>
          <button
            onClick={() => navigate("/companies/new")}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm font-medium"
          >
            + Create New
          </button>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-16">Loading...</div>
        ) : companies.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-xl border border-gray-200">
            <div className="text-4xl mb-4">&#128640;</div>
            <h2 className="text-xl font-semibold text-gray-700 mb-2">
              Create your first AI development team
            </h2>
            <p className="text-gray-500 mb-6">
              Set up a company with a team of AI agents to start building.
            </p>
            <button
              onClick={() => navigate("/companies/new")}
              className="px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium"
            >
              + Create Company
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {companies.map((c) => (
              <div
                key={c.id}
                className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-sm transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`w-2.5 h-2.5 rounded-full ${STATUS_COLORS[c.status] || "bg-gray-300"}`}
                      />
                      <h3 className="font-semibold text-lg">{c.name}</h3>
                    </div>
                    <p className="text-sm text-gray-500">
                      {c.template.charAt(0).toUpperCase() + c.template.slice(1)} template
                      {" \u00b7 "}
                      {STATUS_LABELS[c.status] || c.status}
                      {c.port ? ` \u00b7 Port ${c.port}` : ""}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {c.status === "running" && (
                      <>
                        <button
                          onClick={() => navigate(`/companies/${c.id}/settings`)}
                          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
                        >
                          Settings
                        </button>
                        <button
                          onClick={() =>
                            handleAction(c.id, () => stopInstance(c.id))
                          }
                          disabled={actionLoading === c.id}
                          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                        >
                          Stop
                        </button>
                      </>
                    )}
                    {c.status === "stopped" && (
                      <>
                        <button
                          onClick={() =>
                            handleAction(c.id, () => startInstance(c.id))
                          }
                          disabled={actionLoading === c.id}
                          className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                        >
                          Start
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Delete "${c.name}"? This cannot be undone.`)) {
                              handleAction(c.id, () => deleteCompany(c.id));
                            }
                          }}
                          disabled={actionLoading === c.id}
                          className="px-3 py-1.5 text-sm border border-red-300 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </>
                    )}
                    {c.status === "paused" && (
                      <button
                        onClick={() =>
                          handleAction(c.id, () => startInstance(c.id).catch(() => stopInstance(c.id).then(() => startInstance(c.id))))
                        }
                        disabled={actionLoading === c.id}
                        className="px-3 py-1.5 text-sm bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 disabled:opacity-50"
                      >
                        Resume
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
