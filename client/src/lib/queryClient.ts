import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient();

export function getApiBase() {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  return "";
}

export function getWebSocketUrl(path: string): string {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";

  if (import.meta.env.VITE_API_URL) {
    const url = new URL(import.meta.env.VITE_API_URL);
    return `${wsProtocol}//${url.host}${path}`;
  }

  return `${wsProtocol}//${window.location.host}${path}`;
}

export async function apiRequest(method: string, url: string, data?: unknown | undefined): Promise<Response> {
  const fullUrl = `${getApiBase()}${url}`;
  return fetch(fullUrl, {
    method,
    headers: data ? { "Content-Type": "application/json" } : undefined,
    body: data ? JSON.stringify(data) : undefined,
  }).then((res) => {
    if (!res.ok) {
      throw new Error(`API error: ${res.statusText}`);
    }
    return res;
  });
}
// Temporary mock for sessionStore if it's referenced in home.tsx until a proper auth mechanism is implemented
export const sessionStore = {
  getJobId: (): string | null => null,
  setJobId: (id: string) => { },
};
