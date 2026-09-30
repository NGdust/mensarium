# Security policy

Mensarium runs actions on your machines on behalf of a language model, so security reports get priority.

## Reporting a vulnerability

Please do not open a public issue. Report privately through GitHub: **Security → Report a vulnerability** on the [repository page](https://github.com/NGdust/mensarium/security/advisories/new).

Include the version (`mensarium version`), what an attacker needs (network access to Core, a paired device, control over content the agent reads, and so on), the steps to reproduce, and what they gain.

## Supported versions

Only the latest release receives fixes. Update with `mensarium update`.

## Scope

In scope, among others:

- the model or content it reads (files, web pages, tool output) making a device run something without the required approval, outside the allowed folders or programs, or on another device;
- a client running a request that Core did not sign, a replayed request, or a request whose approval was reused;
- secrets, API keys or login tokens reaching the model, the web UI, logs or a device they were not meant for;
- access to the web UI or the API of Core or a gateway without a valid login.

Out of scope: anything the device owner explicitly allowed (full access, shell, remote updates), actions you approved yourself, and attacks that already require control of the Core host.

How the protections are meant to work is described in [docs/security.md](docs/security.md).
