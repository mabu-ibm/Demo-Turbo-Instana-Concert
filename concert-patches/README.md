# Concert Patches

This directory receives patches from IBM Concert vulnerability remediation workflows.

## How it works

1. Concert identifies a vulnerability in a build artifact
2. Concert generates a patch (e.g., update base image, bump library version)
3. The patch lands in this directory as a `.patch` file or `base-image-override.txt`
4. Run `make patch-build` to apply patches, rebuild, push, and deploy

## Integration options

- **Webhook**: Concert triggers a GitHub webhook, CI runs `make patch-build`
- **Git commit**: Concert bot pushes patches here, triggering CI on push to `main`
- **API**: Concert calls GitHub Actions API to trigger `workflow_dispatch`

## File formats

- `*.patch` — standard git patches applied via `git apply`
- `base-image-override.txt` — single line with new base image (e.g., `python:3.11-slim-bookworm`)
