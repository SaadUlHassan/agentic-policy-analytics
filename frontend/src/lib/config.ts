// Inlined at build time (NEXT_PUBLIC_*). The browser talks to the API directly so that
// REST and WebSocket traffic share one origin and CORS policy.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
