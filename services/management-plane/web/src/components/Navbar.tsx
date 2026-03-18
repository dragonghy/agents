import { useNavigate } from "react-router-dom";
import { logout, type User } from "../lib/api";

interface Props {
  user: User;
}

export default function Navbar({ user }: Props) {
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <button
        onClick={() => navigate("/dashboard")}
        className="text-xl font-bold text-indigo-600 hover:text-indigo-700"
      >
        Agent Hub Cloud
      </button>
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
