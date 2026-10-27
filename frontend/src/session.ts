// Notifications contain no credentials and never retry the failed request.
export function sessionResponse(response: Response) {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event("harness-session-required"));
  }
  return response;
}
