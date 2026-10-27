# Security Policy

## Supported release

Security fixes are handled for the latest released version. Users should update to the latest release when available.

## Reporting a vulnerability

Please do **not** report exploitable vulnerabilities in public issues. Use GitHub's **Report a vulnerability** feature / private vulnerability reporting for this repository if enabled. If private reporting is unavailable, contact the repository maintainers privately through the contact method listed on the GitHub profile. Include affected version, impact, reproduction details, and any suggested mitigation. Do not include real API keys, personal data, or private collection files.

We will acknowledge reports as soon as practical, investigate, and coordinate a fix and disclosure with the reporter. No fixed response-time guarantee is offered for this initial release.

## Security notes

Vinyl Catalog is intended for a trusted local machine or LAN. It binds to `0.0.0.0` by default for LAN access and does not provide authentication or TLS; do not publish port 8501 directly to the internet. Settings include provider credentials in a local plaintext settings file. Restrict access to the OS account and protect backups. Review what data is transmitted before using external AI or Discogs services.
