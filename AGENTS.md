# Development and delivery

Use the existing checkout: cloud tasks already run in isolated environments.
Do not create a Git worktree unless the user explicitly requests one.

Put feature changes on a feature branch and submit a GitHub pull request to
`main` for human approval. Never push feature changes directly to `main`,
auto-merge a PR, or bypass required reviews/status checks.

Read `docs/ci-cd.md` before modifying delivery automation. Do not enable
production releases or automatic production migrations without explicit owner
approval. Never delete, reset, flush, or roll back production data. Use only
disposable local PostgreSQL for tests; do not use a production connection URL.
Workflow and migration changes require owner review.

Run the deployment safety tests (`python -m unittest discover -s tools/tests -v`)
and the repository's documented Django checks/tests for relevant changes. Keep
existing failures visible; do not skip tests or weaken assertions to release.
The initial CI/CD validation and existing PostgreSQL defects are recorded in
`docs/ci-cd.md`.
