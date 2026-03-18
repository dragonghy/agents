import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import CreateCompany from "./pages/CreateCompany";
import CompanySettings from "./pages/CompanySettings";
import AuthGuard from "./components/AuthGuard";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/dashboard"
          element={<AuthGuard>{(user) => <Dashboard user={user} />}</AuthGuard>}
        />
        <Route
          path="/companies/new"
          element={<AuthGuard>{(user) => <CreateCompany user={user} />}</AuthGuard>}
        />
        <Route
          path="/companies/:id/settings"
          element={<AuthGuard>{(user) => <CompanySettings user={user} />}</AuthGuard>}
        />
      </Routes>
    </BrowserRouter>
  );
}
