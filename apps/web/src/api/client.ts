/** Same-origin cookies authenticate every request; signal session expiry to the shell. */
export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const response = await fetch(input, { ...init, credentials: "same-origin" });
  if (response.status === 401) window.dispatchEvent(new Event("tickaw:session-expired"));
  return response;
}
