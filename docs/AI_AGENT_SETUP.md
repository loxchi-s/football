# AI Coding Agent

## Execution model

- Trigger manually from GitHub Actions → Gemini Free AI Coding Agent → Run workflow.
- Runs on the GitHub-hosted `ubuntu-latest` standard runner; no GPU or local machine is used.
- Uses Google Gemini Developer API model `gemini-3.5-flash-lite`, currently listed with free input/output pricing.
- Requires the repository Actions secret `GEMINI_API_KEY`.
- The workflow stops on missing key, quota/rate limit, or API failure. There is no paid fallback.
- The workflow is split into two isolated jobs: generation/validation has read-only repository permission; publishing runs on a fresh runner with write permission and never executes generated code.
- Proposed changes are checked with Ruff, compileall, and pytest before a patch artifact is passed to the publisher.

## Data and permission boundaries

- The agent receives only tracked text files under `scripts/`, `tests/`, `docs/`, and a small allowlist of root project configuration files.
- It cannot change `.github/workflows/`, its own policy script, the Master workbook, or production database configuration.
- No database credentials, workbook, or production data are passed to Gemini.
- Agent changes are passed as a short-lived patch artifact to a clean publisher runner, then pushed to a new `ai-agent/run-<id>` branch and submitted as a PR. The publisher does not execute generated code. The agent cannot merge.
- Review the generated diff before merging. The agent is not a substitute for code review.

## One-time setup

1. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Do not link Google Cloud Billing or upgrade to a paid tier.
3. In GitHub, open Settings → Secrets and variables → Actions → New repository secret.
4. Set the name to `GEMINI_API_KEY` and paste the key into the secret value field. Never paste it into chat, source files, or workflow inputs.
5. In Settings → Actions → General, ensure GitHub Actions is allowed to create pull requests if PR creation is blocked.

## Free-tier and privacy limits

- Free-tier quota is limited and can change. HTTP 403/429 or quota errors stop the run; no paid model fallback exists.
- Google states that free-tier content may be used to improve its products. Submit only public, non-sensitive code and task details.
- A free model tier does not guarantee uninterrupted availability or a fixed request quota.


## API connectivity smoke test

- Run **GitHub Actions → Gemini API Smoke Test → Run workflow** to test the API without invoking the coding agent.
- Select `gemini-3.5-flash-lite` (default) or `gemini-3.8-flash`.
- This workflow only makes one structured JSON generation request. It has read-only repository permission, does not modify files, create artifacts, create branches, or open pull requests.
- A successful run confirms API access for the selected model at that time; it does not guarantee future quota or availability.
