# Security model

nvpulse is a local, read-mostly terminal app. It doesn't listen on the network,
store data or need privileges. Still, it displays data other people control, it
can send signals, and it can exec another binary, so those three areas are hardened.

## Threat model

| Actor | Can control | Goal |
|---|---|---|
| Another local user on a shared GPU machine | Their own processes' names and argv, files in directories they can write | Attack the person running nvpulse (often an admin, sometimes root) |
| Anyone screen-sharing or recording | Nothing; they just see the screen | Read secrets that appear in command lines |
| Supply chain | Dependencies, GitHub Actions | Compromise users or the repo |

Out of scope: an attacker who already controls your environment variables,
Python install or terminal. They already have code execution as you.

## Mitigations

### 1. Terminal escape and markup injection: `src/nvpulse/sanitize.py`

**Risk.** A process can set its argv to contain raw escape sequences, e.g.
`exec -a $'\e]0;owned\e\\\e[2J' python`. Textual strips only BEL, BS, VT, FF and CR,
so ESC (`0x1b`) and C1 controls (`0x9b`) would pass straight to the viewer's
terminal. Depending on the terminal, that allows title or clipboard writes
(OSC 0/52), screen clearing to hide things, or historically worse. Bidi overrides
(`U+202E`) and zero-width characters can make `evil` look like `python3 train.py`.
Separately, any string rendered as Textual markup could forge or break UI text:
a process named `[/]` used to crash the app when its kill dialog opened.

**Mitigation.**

- Every process name, user and command line passes through `clean()` in
  `procinfo.enrich()`, and again at render time. `clean()` turns every character
  in Unicode categories Cc, Cf, Zl, Zp, Co, Cs and Cn into a visible `\xNN` /
  `\uNNNN` escape, and caps the length (command line 1024, name 64, user 32).
  Untrusted data can't inject escapes, and huge argv strings can't stall rendering.
- NVML strings (GPU name, bus ID) and the hostname are cleaned the same way.
- Untrusted text is only rendered as `rich.text.Text` or with `markup=False`.
  Border titles are set as `Text` as well: Textual parses a *string* title as
  markup, and its `escape()` only covers complete `[tags]`, so a name cut off
  mid-tag could swallow markup that follows it. Notifications go through
  `App._say()`, which disables markup.

### 2. Secrets in command lines: `sanitize.redact()`

**Risk.** People pass tokens on the command line (`--api-key`, `HF_TOKEN=…`,
`postgres://user:pass@…`). Linux already lets any user read other users' argv
through `/proc`, but a dashboard that shows them in large type on a shared screen,
in a screenshot or in a recording makes leaks much more likely.

**Mitigation.** Values for flags ending in password, passwd, pass, pwd, secret,
token, api-key, access-key, auth-token, bearer, credential(s), private-key or
client-secret, plus `*TOKEN*` / `*SECRET*` / `*PASSWORD*` style `KEY=value` pairs
and URL user-info passwords, are shown as `•••`. This is on by default;
`--no-redact` turns it off. It's a best-effort heuristic, not a guarantee.

### 3. Killing the wrong process: `src/nvpulse/killer.py`

**Risk.** Between the poll that listed a process and the moment you press `y`,
the process can exit and its PID can be reused. As root, a stale PID could
SIGKILL an unrelated system service. NVML can also report PID 0 for processes
in other PID namespaces, and `kill(0, …)` signals your *own* process group.

**Mitigation.**

- PIDs ≤ 1, nvpulse's own PID and its parent are refused outright.
- When the dialog opens, the target is pinned with a **pidfd**
  (`os.pidfd_open`, Linux 5.3+), and its kernel start time is checked against
  the snapshot. A mismatch means the PID was reused, and nvpulse refuses.
- The signal goes through `signal.pidfd_send_signal`, so it can only reach the
  pinned process. On kernels without pidfd, the start time is re-checked
  immediately before `os.kill`.
- The process must still be on the GPU in the latest poll.
- The dialog shows the owner. When running as root it adds a warning, and the
  header shows a red **ROOT** badge.
- `--read-only` disables `k` / `K` entirely.
- In mock mode, no real PID is ever opened or signalled.

### 4. Executing `nvidia-smi`: `cli.find_real_nvidia_smi()`

**Risk.** Passthrough execs whatever `nvidia-smi` it finds. An empty or relative
`PATH` entry means "the current directory", so running nvpulse from a directory
holding a planted `nvidia-smi` would execute it. Under `sudo`, a user-writable
binary on `PATH` would run as root. An `nvidia-smi` wrapper that calls nvpulse
again would loop forever.

**Mitigation.**

- Empty and relative `PATH` entries are skipped.
- Candidates must be regular executable files that aren't world-writable, in
  a directory that isn't world-writable (unless sticky). When running as root,
  the file and its directory must be owned by root and the file must not be
  group-writable.
- `NVPULSE_REAL_SMI` must pass the same checks.
- `os.execve` is used with an argument list. No shell is involved, so arguments
  are passed verbatim.
- A `NVPULSE_PASSTHROUGH` marker in the environment detects and stops recursion.
- `allow_abbrev=False` means an abbreviated nvidia-smi flag (e.g. `--comp`) is
  never captured as one of nvpulse's own flags.

### 5. Input validation and resource limits

- `--interval` is clamped to 0.1–3600 s, `--fps` to 1–60, and `--mock` to 1–64.
  NaN and infinity are rejected.
- `-i` accepts at most 64 selectors, each a non-negative integer, a `GPU-…` UUID
  or a PCI bus ID, matched by anchored regular expressions. Anything else is
  rejected before a backend is created.
- History buffers are fixed-size deques. The PID info cache is pruned every poll.
- The `/proc/<pid>/cmdline` fallback reads at most 64 KiB.

### 6. Reduced UI surface

Textual's command palette is disabled (`ENABLE_COMMAND_PALETTE = False`). nvpulse
doesn't use it, and it adds actions such as saving screenshots to the current directory.

### 7. `--dump` output

**Risk.** A diagnostic dump gets pasted into public issues. Hostnames, GPU
UUIDs, user names and command lines identify people and machines, and command
lines can hold secrets that the redaction heuristic misses.

**Decision.** `--dump` writes one JSON document to stdout and nowhere else: no
file, no network. It omits the hostname, replaces the GPU UUID with a
placeholder, and reports processes as type and numbers only (no PID, name, user
or command line), so it never reads `/proc` at all. Output is ASCII-only JSON,
so no driver string can carry a control character to the terminal.

### 8. Supply chain and CI

- The CI workflow runs with `permissions: contents: read`, and checkouts use
  `persist-credentials: false`.
- The release workflow only runs when a maintainer starts it by hand from a
  version tag; no push, tag or release triggers it. It uploads to PyPI through
  trusted publishing (OIDC), so no API token exists to steal.
  `id-token: write` is granted to the publish job alone, which runs no code
  from the repository: it downloads the artifact the build job made.
- Every third-party action is pinned to a full commit SHA. Dependabot updates
  both actions and Python dependencies weekly.
- A `pip-audit --strict` job fails CI on known-vulnerable dependencies.
- Triggers are `push` and `pull_request` only, never `pull_request_target`.
- Dependency floors are set to versions the test suite actually passes on
  (Textual ≥ 4.0).

## Guidance for users

- **Prefer not to run nvpulse as root.** You see your own processes without it.
  On most systems you see everyone's GPU processes too, just not always their
  user or command line. If you do use `sudo`, consider `--read-only`.
- **Screen-sharing:** keep redaction on (the default), and remember it's a heuristic.
- **Don't set `TEXTUAL=devtools` on shared machines.** It makes the app stream
  its screen to a local devtools socket that another user could be listening on.

- **Before sharing a `--dump`,** skim it. It is built to be shareable, but GPU
  model, driver version and kernel version are in there by design.

## Known limitations

- Redaction can't catch every secret format, and it can't help if a tool prints
  secrets in its process *name*.
- On kernels without pidfd (before 5.3), a very small race remains between the
  start-time check and `kill()`.
- nvpulse trusts the NVIDIA driver (NVML) and your terminal emulator.
