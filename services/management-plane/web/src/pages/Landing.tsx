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
            <div className="text-4xl mb-3">&#9889;</div>
            <h3 className="font-semibold text-lg mb-2">Instant Setup</h3>
            <p className="text-gray-600 text-sm">
              Register, choose a team template, and your AI agents start working in under 5 minutes.
            </p>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
            <div className="text-4xl mb-3">&#128736;</div>
            <h3 className="font-semibold text-lg mb-2">Zero Ops</h3>
            <p className="text-gray-600 text-sm">
              No tmux, no Docker, no daemon management. Everything is handled by the platform.
            </p>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
            <div className="text-4xl mb-3">&#128065;</div>
            <h3 className="font-semibold text-lg mb-2">Full Visibility</h3>
            <p className="text-gray-600 text-sm">
              Monitor agent activity, review code, manage tasks - all through a web dashboard.
            </p>
          </div>
        </div>

        {/* Pricing */}
        <div className="mt-20">
          <h2 className="text-3xl font-bold text-center mb-10">Simple Pricing</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-left">
            <div className="bg-white p-6 rounded-xl shadow-sm border-2 border-indigo-500 relative">
              <span className="absolute -top-3 left-6 bg-indigo-600 text-white text-xs px-3 py-1 rounded-full">
                Current
              </span>
              <h3 className="font-bold text-xl mb-1">Free Beta</h3>
              <div className="text-3xl font-bold mb-4">$0<span className="text-sm text-gray-400 font-normal">/mo</span></div>
              <ul className="space-y-2 text-sm text-gray-600">
                <li>&#10003; Up to 3 companies</li>
                <li>&#10003; All team templates</li>
                <li>&#10003; Community support</li>
                <li>&#10003; Bring your own Claude subscription</li>
              </ul>
              <Link
                to="/register"
                className="mt-6 block w-full text-center py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium"
              >
                Get Started
              </Link>
            </div>
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 opacity-75">
              <h3 className="font-bold text-xl mb-1">Starter</h3>
              <div className="text-3xl font-bold mb-4">$29<span className="text-sm text-gray-400 font-normal">/mo</span></div>
              <ul className="space-y-2 text-sm text-gray-600">
                <li>&#10003; 1 company</li>
                <li>&#10003; Standard template</li>
                <li>&#10003; Email support</li>
                <li>&#10003; Usage analytics</li>
              </ul>
              <button
                disabled
                className="mt-6 w-full py-2.5 border border-gray-200 rounded-lg text-gray-300 cursor-not-allowed text-sm"
              >
                Coming soon
              </button>
            </div>
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 opacity-75">
              <h3 className="font-bold text-xl mb-1">Pro</h3>
              <div className="text-3xl font-bold mb-4">$99<span className="text-sm text-gray-400 font-normal">/mo</span></div>
              <ul className="space-y-2 text-sm text-gray-600">
                <li>&#10003; 5 companies</li>
                <li>&#10003; All templates</li>
                <li>&#10003; Priority support</li>
                <li>&#10003; Advanced analytics</li>
              </ul>
              <button
                disabled
                className="mt-6 w-full py-2.5 border border-gray-200 rounded-lg text-gray-300 cursor-not-allowed text-sm"
              >
                Coming soon
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
