# Security

`agent-yaml` spawns external coding-agent CLIs with prompts read from YAML workflow files. Treat
workflow files as executable input.

## Reporting a vulnerability

Please report vulnerabilities privately via GitHub's private vulnerability reporting:

https://github.com/roboalchemist/agent-yaml/security/advisories/new

Do not open a public issue for security problems. Include the workflow file, the command you ran,
and the observed impact. You should get a response within a few days.

## Scope notes

- Workflow YAML can set `directory`, `env`, `raw-args` and prompts that are passed to the agent CLI.
  Only run workflows you trust.
- Credentials are read from the environment or from the agent CLI's own configuration; `agent-yaml`
  does not store secrets itself.
