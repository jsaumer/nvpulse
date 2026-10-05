# Security Policy

## Supported versions

nvpulse is pre-1.0. Security fixes go into the latest release only.

| Version | Supported |
|---|---|
| latest `0.x` | ✅ |
| older | ❌ |

## Reporting a vulnerability

Please **don't open a public issue** for security problems.

The repository is currently private, so report directly to the maintainer at
the address in `pyproject.toml`. (GitHub's private vulnerability reporting,
**Security → Report a vulnerability**, only exists for public repositories; it
becomes the route if this one is opened up.) Include:

- what an attacker can do and under which conditions (local user? needs root?)
- steps or a proof of concept (a crafted process name, a PATH layout, …)
- your nvpulse version (`nvpulse --version`), OS, terminal and driver version

You can expect an acknowledgement within a week. Once a fix is released, you'll
be credited in the changelog unless you'd rather not be.

## Scope

nvpulse runs locally and has no network listener. The interesting attack surface is:

- **Untrusted text on screen.** Process names and command lines are chosen by
  whoever started the process. That includes other users on a shared GPU box.
- **Signalling processes** (`k` / `K`), especially when nvpulse runs as root.
- **Executing the real `nvidia-smi`** in passthrough mode (PATH lookup).
- **The settings file**, which can turn off redaction and read-only mode.
- **What `--dump` and `--once` print**, since both get pasted and piped elsewhere.
- **The CI / release supply chain.**

[docs/security.md](docs/security.md) has the threat model and the mitigations in place.
