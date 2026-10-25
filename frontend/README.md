# Frontend

Next.js 16 (App Router) + TypeScript + Tailwind. Talks to the FastAPI backend directly at
`NEXT_PUBLIC_API_URL` (inlined at build time; default `http://localhost:8000`).

```bash
npm ci
npm run dev        # http://localhost:3000
npm test           # Vitest + Testing Library
npm run lint && npm run typecheck && npm run build
```

See the repository root README and `docs/IMPLEMENTATION_PLAN.md` for the full system.
