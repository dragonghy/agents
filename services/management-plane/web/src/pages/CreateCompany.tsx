import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createCompany, type User } from "../lib/api";
import Navbar from "../components/Navbar";

const TEMPLATES = [
  {
    id: "solo",
    name: "Solo",
    desc: "3 agents: 1 Product + 1 Dev + 1 QA",
    agents: 3,
  },
  {
    id: "standard",
    name: "Standard",
    desc: "5 agents: 1 Product + 2 Dev + 1 QA + 1 User Tester",
    agents: 5,
  },
  {
    id: "full",
    name: "Full",
    desc: "8+ agents: Product, Dev, QA, Admin, Inspector, User",
    agents: 8,
  },
];

const AUTH_TYPES = [
  {
    id: "oauth_token",
    name: "OAuth Token",
    desc: "For Claude Pro/Max subscribers. Run 'claude setup-token' to get your token.",
    placeholder: "sk-ant-oat-...",
  },
  {
    id: "api_key",
    name: "API Key",
    desc: "For Anthropic API users (pay-per-use).",
    placeholder: "sk-ant-api03-...",
  },
];

interface Props {
  user: User;
}

export default function CreateCompany({ user }: Props) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Step 1
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  // Step 2
  const [template, setTemplate] = useState("standard");

  // Step 3
  const [authType, setAuthType] = useState("oauth_token");
  const [authToken, setAuthToken] = useState("");

  const autoSlug = (n: string) => {
    return n
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
  };

  const handleNameChange = (v: string) => {
    setName(v);
    if (!slug || slug === autoSlug(name)) {
      setSlug(autoSlug(v));
    }
  };

  const handleSubmit = async () => {
    setError("");
    setLoading(true);
    try {
      await createCompany({
        name,
        slug: slug || undefined,
        template,
        auth_type: authType,
        auth_token: authToken || undefined,
      });
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Creation failed");
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar user={user} />

      <main className="max-w-2xl mx-auto px-6 py-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Create Company</h1>

        {/* Progress steps */}
        <div className="flex items-center gap-2 mb-8">
          {[1, 2, 3, 4].map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                  s <= step
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-200 text-gray-500"
                }`}
              >
                {s}
              </div>
              {s < 4 && <div className={`w-12 h-0.5 ${s < step ? "bg-indigo-600" : "bg-gray-200"}`} />}
            </div>
          ))}
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>
        )}

        <div className="bg-white p-8 rounded-xl shadow-sm border border-gray-200">
          {/* Step 1: Company Info */}
          {step === 1 && (
            <>
              <h2 className="text-lg font-semibold mb-4">Company Info</h2>
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Company Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                  placeholder="My Startup"
                />
              </div>
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Slug (URL identifier)
                </label>
                <input
                  type="text"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                  placeholder="my-startup"
                />
                <p className="text-xs text-gray-400 mt-1">
                  {slug}.agenthub.cloud
                </p>
              </div>
              <button
                onClick={() => name && setStep(2)}
                disabled={!name}
                className="px-6 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium disabled:opacity-50"
              >
                Next
              </button>
            </>
          )}

          {/* Step 2: Team Template */}
          {step === 2 && (
            <>
              <h2 className="text-lg font-semibold mb-4">Team Configuration</h2>
              <div className="space-y-3 mb-6">
                {TEMPLATES.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setTemplate(t.id)}
                    className={`w-full text-left p-4 rounded-lg border-2 transition-colors ${
                      template === t.id
                        ? "border-indigo-600 bg-indigo-50"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{t.name}</span>
                      <span className="text-sm text-gray-500">{t.agents} agents</span>
                    </div>
                    <p className="text-sm text-gray-500 mt-1">{t.desc}</p>
                  </button>
                ))}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep(1)}
                  className="px-6 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium"
                >
                  Back
                </button>
                <button
                  onClick={() => setStep(3)}
                  className="px-6 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium"
                >
                  Next
                </button>
              </div>
            </>
          )}

          {/* Step 3: Authentication */}
          {step === 3 && (
            <>
              <h2 className="text-lg font-semibold mb-4">Claude Code Authentication</h2>
              <div className="space-y-3 mb-4">
                {AUTH_TYPES.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => setAuthType(a.id)}
                    className={`w-full text-left p-4 rounded-lg border-2 transition-colors ${
                      authType === a.id
                        ? "border-indigo-600 bg-indigo-50"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <span className="font-medium">{a.name}</span>
                    <p className="text-sm text-gray-500 mt-1">{a.desc}</p>
                  </button>
                ))}
              </div>
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Token / Key
                </label>
                <input
                  type="password"
                  value={authToken}
                  onChange={(e) => setAuthToken(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none font-mono text-sm"
                  placeholder={AUTH_TYPES.find((a) => a.id === authType)?.placeholder}
                />
                <p className="text-xs text-gray-400 mt-1">
                  Optional for development. Required for production use.
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep(2)}
                  className="px-6 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium"
                >
                  Back
                </button>
                <button
                  onClick={() => setStep(4)}
                  className="px-6 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium"
                >
                  Next
                </button>
              </div>
            </>
          )}

          {/* Step 4: Confirm */}
          {step === 4 && (
            <>
              <h2 className="text-lg font-semibold mb-4">Confirm & Create</h2>
              <div className="space-y-3 mb-6 bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between">
                  <span className="text-gray-600">Company</span>
                  <span className="font-medium">{name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Slug</span>
                  <span className="font-medium">{slug || autoSlug(name)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Template</span>
                  <span className="font-medium capitalize">{template}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Auth Type</span>
                  <span className="font-medium">
                    {AUTH_TYPES.find((a) => a.id === authType)?.name}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Token</span>
                  <span className="font-medium">
                    {authToken ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" : "(not set)"}
                  </span>
                </div>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep(3)}
                  className="px-6 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium"
                >
                  Back
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={loading}
                  className="px-6 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium disabled:opacity-50"
                >
                  {loading ? "Creating..." : "Create Company"}
                </button>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
