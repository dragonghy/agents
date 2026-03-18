import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getMe, isLoggedIn, type User } from "../lib/api";

interface Props {
  children: (user: User) => React.ReactNode;
}

export default function AuthGuard({ children }: Props) {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isLoggedIn()) {
      navigate("/login");
      return;
    }
    getMe()
      .then(setUser)
      .catch(() => navigate("/login"))
      .finally(() => setLoading(false));
  }, [navigate]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  if (!user) return null;
  return <>{children(user)}</>;
}
