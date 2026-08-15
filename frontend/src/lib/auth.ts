const TOKEN_KEY = "darkpulse.access_token";
export const UNAUTHENTICATED_EVENT = "darkpulse:unauthenticated";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
}

export function notifyUnauthenticated(): void {
  clearAccessToken();
  window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
}
