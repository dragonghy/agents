import { Link } from "react-router-dom";
import { isLoggedIn } from "../lib/api";

export default function Landing() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-purple-50">
      <nav className="px-6 py-4 flex items-center justify-between max-w-6xl mx-auto">
        <span className="text-xl font-bold text-indigo-600">Agent Hub Cloud</span>
        <div className="flex gap-3">
          {isLoggedIn() ? (
            <Link
              to="/dashboard"
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm font-medium"
            >
              Dashboard
            </Link>
          ) : (
            <>
              <Link
                to="/login"
                className="px-4 py-2 text-gray-700 hover:text-gray-900 text-sm font-medium"
              >
                Log in
              </Link>
              <Link
                to="/register"
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm font-medium"
              >
                Get Started
              </Link>
            </>
          )}
        </div>
      </nav>

      <main className="max-w-4xl mx-auto px-6 pt-20 pb-32 text-center">
        <h1 className="text-5xl font-bold text-gray-900 mb-6">
          Your AI Development Team
          <br />
          <span className="text-indigo-600">in the Cloud</span>
        </h1>
        <p className="text-xl text-gray-600 mb-10 max-w-2xl mx-auto">
          Deploy a complete multi-agent development team in minutes.
          Zero infrastructure, zero ops. Just define your project and let AI agents build it.
        </p>
        <Link
          to="/register"
          className="inline-block px-8 py-4 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-lg font-semibold shadow-lg shadow-indigo-200"
        >
          Get Started Free
        </Link>

        <div className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-8 text-left">
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
            <div className="text-2xl mb-3">&#9889;</div>
            <h3 className="font-semibold text-lg mb-2">Instant Setup</h3>
            <p className="text-gray-600 text-sm">
              Register, choose a team template, and your AI agents start working in under 5 minutes.
            </p>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
            <div className="text-2xl mb-3">&#128736;</div>
            <h3 className="font-semibold text-lg mb-2">Zero Ops</h3>
            <p className="text-gray-600 text-sm">
              No tmux, no Docker, no daemon management. Everything is handled by the platform.
            </p>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
            <div className="text-2xl mb-3">&#128065;</div>
            <h3 className="font-semibold text-lg mb-2">Full Visibility</h3>
            <p className="text-gray-600 text-sm">
              Monitor agent activity, review code, manage tasks - all through a web dashboard.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
