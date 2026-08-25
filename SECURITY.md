# Security policy

Lacuna is pre-alpha and does not yet publish supported release lines. Please do not open a public issue for a suspected vulnerability. Contact the maintainers privately through the repository host's security-advisory feature once the canonical repository is published.

Security-sensitive design rules include:

- never use pickle as the default cache or report interchange;
- treat in-process Arrow C Data and C Stream pointers as trusted-producer boundaries;
- never install or execute plugins from an audit artifact;
- escape user-provided metadata in future HTML renderers;
- validate external analytical files through format-aware readers.

Reports should include enough version and provenance information for a fix to be verified against the affected method implementation.
