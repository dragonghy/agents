/**
 * API client for Management Plane backend.
 */

const API_BASE = "/api";

function getToken(): string | null {
  return localStorage.getItem("token");
}

export function setToken(token: string): void {
  localStorage.setItem("token", token);
}

export function clearToken(): void {
  localStorage.removeItem("token");
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${resp.status}`);
  }

  return resp.json();
}

// ── Auth ──

export interface User {
  id: string;
  email: string;
  name: string | null;
}

export async function register(
  email: string,
  password: string,
  name?: string
): Promise<{ user: User; token: string }> {
  const data = await request<{ user: User; token: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
  setToken(data.token);
  return data;
}

export async function login(
  email: string,
  password: string
): Promise<{ user: User; token: string }> {
  const data = await request<{ user: User; token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(data.token);
  return data;
}

export async function logout(): Promise<void> {
  await request("/auth/logout", { method: "POST" }).catch(() => {});
  clearToken();
}

export async function getMe(): Promise<User> {
  const data = await request<{ user: User }>("/auth/me");
  return data.user;
}

// ── Companies ──

export interface Company {
  id: string;
  name: string;
  slug: string;
  status: string;
  template: string;
  auth_type: string | null;
  port: number | null;
  url?: string;
  created_at: string;
  updated_at: string;
}

export async function listCompanies(): Promise<Company[]> {
  const data = await request<{ companies: Company[] }>("/companies");
  return data.companies;
}

export async function createCompany(params: {
  name: string;
  slug?: string;
  template?: string;
  auth_type?: string;
  auth_token?: string;
}): Promise<Company> {
  const data = await request<{ company: Company }>("/companies", {
    method: "POST",
    body: JSON.stringify(params),
  });
  return data.company;
}

export async function getCompany(id: string): Promise<Company> {
  const data = await request<{ company: Company }>(`/companies/${id}`);
  return data.company;
}

export async function updateCompany(
  id: string,
  params: Partial<Pick<Company, "name" | "slug" | "template">>
): Promise<Company> {
  const data = await request<{ company: Company }>(`/companies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(params),
  });
  return data.company;
}

export async function deleteCompany(id: string): Promise<void> {
  await request(`/companies/${id}`, { method: "DELETE" });
}

// ── Instance lifecycle ──

export async function startInstance(id: string): Promise<{ status: string }> {
  return request(`/companies/${id}/start`, { method: "POST" });
}

export async function stopInstance(id: string): Promise<{ status: string }> {
  return request(`/companies/${id}/stop`, { method: "POST" });
}

export async function pauseInstance(id: string): Promise<{ status: string }> {
  return request(`/companies/${id}/pause`, { method: "POST" });
}

export async function resumeInstance(id: string): Promise<{ status: string }> {
  return request(`/companies/${id}/resume`, { method: "POST" });
}

export async function getInstanceStatus(
  id: string
): Promise<{ status: string; port: number | null; mock_mode: boolean }> {
  return request(`/companies/${id}/status`);
}

// ── Auth config ──

export async function updateAuth(
  id: string,
  authType: string,
  authToken: string
): Promise<Company> {
  const data = await request<{ company: Company }>(`/companies/${id}/auth`, {
    method: "PUT",
    body: JSON.stringify({ auth_type: authType, auth_token: authToken }),
  });
  return data.company;
}
