# Vyapari AI — Project Context

Goal: multilingual voice-first AI business manager for small businesses, accessed via web, WhatsApp and phone. Initial target: Indian retailers, including Telugu/Hindi/English speakers.

## Current state
- frontend/: React 19 + Vite 6 + plain CSS + lucide-react + Recharts. Functional local demo with in-memory sample products, customers, orders, analytics, storefront preview, and rules-based chat. Data is NOT persistent.
- backend/: FastAPI skeleton with GET / and GET /health. No database, authentication or external APIs.
- UI demo brand "Vyapari AI" is provisional. Demo business "sadguru Boutique" is fictional.

## Required eventual modules
Multi-tenant auth and authorization, products/inventory, customers, orders, sales analytics, template-driven AI website builder, multilingual AI assistant, speech I/O, WhatsApp owner commands and customer support, phone calls, advertising approval workflow, billing, deployment.

## Development rules
- Inspect existing files before changing anything. Preserve UI where possible.
- Build incrementally; prioritize real auth, database, RLS, APIs and persistence first.
- Do not treat demo values as actual sales or real customer information.
- Verify server-side tenant authorization on every operation. No arbitrary SQL or shell execution by AI.
- Confirm high-risk writes, outbound messages, advertising spend and payments.
- Keep secrets in environment variables, never commit credentials.
- Use PowerShell-compatible commands for Windows.
- Implement one module per task. Run relevant tests/builds; report changes, tests, blockers briefly.
- Ask before purchases, deployments, destructive operations or changing core architecture.
