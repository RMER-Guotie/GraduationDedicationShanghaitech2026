# Codex Project Rules

This file is the source of truth for collaboration rules in this project.
Read this file before making any plan, code change, document change, build, run,
or other high-cost action.

## Scope

- The correct project directory is:
  `C:\Users\RMER_guotie\Desktop\graduation\pixel`
- Do not use or modify:
  `C:\Users\RMER_guotie\Desktop\graduation\bsrr_test`
- `CODEX_HANDOFF.md` records architecture, implementation status, hardware
  mapping, RAM/protocol decisions, progress, and known issues.
- `CODEX_RULES.md` records collaboration rules, permissions, and workflow.

## Reply Rules

- Every reply must start with `guotie你好`.
- Every reply must end with a concise statement of the expected nature of the
  user's next prompt.
- The expected next prompt must be exactly one of these two categories:
  - `给出信息`: the user should provide more information, opinions, constraints,
    or design choices.
  - `授权`: the user should explicitly approve a proposed code/document change,
    build/run action, or other costly action.
- `给出信息` and `授权` are mutually exclusive.

## Information And Authorization Flow

- If information is incomplete, keep asking for information or list pending
  confirmation items. Do not modify code or documents at the same time.
- When information is sufficient, provide a concrete implementation or document
  change plan first, then ask for authorization.
- Do not modify code, documents, `.ioc`, generated files, project files, or run
  build/test tools until the user has authorized that specific action.
- If the user does not authorize, or provides new design feedback, continue
  information gathering or revise the plan.
- Editing `CODEX_RULES.md` or `CODEX_HANDOFF.md` is itself subject to this same
  information and authorization flow.

## Code And Project Change Rules

- Prefer adding application-level modules over putting business logic into
  Cube-generated files.
- Do not modify Cube-generated code outside `/* USER CODE BEGIN ... */` and
  `/* USER CODE END ... */` blocks unless the user explicitly authorizes the
  specific change.
- Do not modify `.ioc` unless the user explicitly authorizes the specific `.ioc`
  change.
- Do not directly refactor the project unless the user explicitly authorizes the
  refactor plan.
- Preserve unrelated user changes in the working tree.

## Build And Run Rules

- Do not run the local compiler, Keil build, tests, or runtime tools by default.
- After each implementation phase, either the user builds manually or explicitly
  authorizes Codex to build/run.
- Ask for authorization before any action that is time-consuming, costly, or may
  consume substantial context/tool budget.

