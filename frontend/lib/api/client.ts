import type { ApiResponse } from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export async function apiRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(
    `${API_URL}${path}`,
    {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    },
  );

  let payload: ApiResponse<T>;

  try {
    payload = await response.json();
  } catch {
    throw new Error(
      `Backend returned invalid JSON (${response.status})`,
    );
  }

  if (!response.ok || !payload.success) {
    if (!payload.success) {
      throw new Error(payload.error.message);
    }

    throw new Error(
      `Backend request failed (${response.status})`,
    );
  }

  return payload.data;
}