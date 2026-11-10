# AI Coding Agent

## Current repository automation

- GitHub Actions runs CI, Ruff, compilation, unit tests, and CodeQL.
- Dependabot proposes dependency updates weekly.
- Agent changes must be delivered through pull requests; never write directly to `main`.
- Do not modify the Master workbook or production database from an agent workflow.
- Do not put API keys, PATs, database URLs, or workbook files in git.

## OpenHands activation is not yet configured

OpenHands requires an LLM provider endpoint/key and GitHub write permissions to create branches and pull requests. The provider may incur charges; a free GitHub Actions runner does not make model inference free.

The older `All-Hands-AI/openhands-resolver` repository is archived, so this project does not install that unmaintained resolver. Configure a currently supported OpenHands SDK/hosted runner only after selecting a model endpoint and adding its secret through GitHub Settings → Secrets and variables → Actions.

Never grant an agent unrestricted repository administration, secret access, or permission to bypass required checks.
