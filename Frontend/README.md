# Frontend

## Folder purpose

This directory contains the React client application. Keep browser-facing code and frontend-only tooling here.

| Path | Purpose |
| --- | --- |
| `public/` | Static files served without bundling, such as favicons and manifest files. |
| `src/assets/` | Images, fonts, icons, and other imported application assets. |
| `src/components/` | Reusable UI components. |
| `src/pages/` | Route-level screens. |
| `src/layouts/` | Shared page shells and layout components. |
| `src/hooks/` | Reusable React hooks. |
| `src/services/` | API clients and other external-service integrations. |
| `src/context/` | React context providers and related state. |
| `src/utils/` | Small, framework-independent helper functions. |
| `src/styles/` | Global styles, design tokens, and shared style utilities. |
| `src/tests/` | Frontend tests and test helpers. |

## Coding standards

- Use functional components and hooks; keep each component focused on one responsibility.
- Use clear, descriptive names. Components use `PascalCase`; hooks start with `use`; utilities use `camelCase`.
- Keep API calls in `src/services/`, not inside page or presentational components.
- Prefer reusable components and shared styles over duplicated markup or CSS.
- Do not commit secrets, generated dependency folders, build output, or local environment files.
- Run the project's formatter, linter, and tests before opening a pull request once they are configured.

## Start React

After a React project has been initialized in this directory, install and start it with:

```bash
cd Frontend
npm install
npm run dev
```

For a new Vite-based React application, initialize the project from the repository root before the first install:

```bash
npm create vite@latest Frontend -- --template react
```

Do not overwrite the shared folder layout when initializing the application.

## Git workflow for frontend

1. Create a focused branch from the current integration branch, for example `feature/frontend-login`.
2. Make small, related commits using clear imperative messages.
3. Rebase or merge the current integration branch before requesting review, following the team's chosen policy.
4. Open a pull request that describes the UI change, testing performed, and any API dependency.
5. Obtain review and passing checks before merging. Do not commit directly to the protected integration branch.
