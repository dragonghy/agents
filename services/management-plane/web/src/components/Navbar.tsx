import { useNavigate, useLocation } from "react-router-dom";
import { logout, type User } from "../lib/api";

interface Props {
  user: User;
}

export default function Navbar({ user }: Props) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const navLinks = [
    { path: "/dashboard", label: "Dashboard" },
    { path: "/companies", label: "Companies" },
  ];

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <button
          onClick={() => navigate("/dashboard")}
          className="text-xl font-bold text-indigo-600 hover:text-indigo-700"
        >
          Agent Hub Cloud
        </button>
        <div className="hidden sm:flex items-center gap-1">
          {navLinks.map((link) => {
            const isActive = location.pathname === link.path;
            return (
              <button
                key={link.path}
                onClick={() => navigate(link.path)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
                }`}
              >
                {link.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-sm text-gray-600">{user.email}</span>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          Log out
        </button>
      </div>
    </nav>
  );
}
