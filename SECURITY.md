# Security Policy

## Supported versions

nvpulse is pre-1.0. Security fixes go into the latest release only.

| Version | Supported |
|---|---|
| latest `0.x` | ✅ |
| older | ❌ |

## Reporting a vulnerability

Please **don't open a public issue** for security problems.

Report it privately instead, either way works:

- through GitHub: the repository's **Security** tab → **Report a vulnerability**
  ([direct link](https://github.com/jsaumer/nvpulse/security/advisories/new))
- by email to the maintainer, at the address in `pyproject.toml`

Include:

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
