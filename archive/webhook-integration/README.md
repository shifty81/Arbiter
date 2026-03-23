# Archive — Webhook Integration

This folder contains the original ArbiterAI webhook integration that bridged **Jira**, **Azure Boards**, and **Linear** with the GitHub Copilot coding agent.

This code has been archived as the repository's focus has shifted to the **Arbiter AI** personal autonomous development assistant (see root `README.md`).

## Contents

- `src/` — TypeScript source code (Express server, webhook handlers, GitHub client)
- `tests/` — Jest test suite
- `package.json` — Node.js project manifest
- `tsconfig.json` — TypeScript configuration
- `jest.config.ts` — Jest configuration
- `.env.example` — Environment variable template

## Running the archived integration

```bash
cd archive/webhook-integration
npm install
cp .env.example .env
# Edit .env with credentials
npm run dev
```
