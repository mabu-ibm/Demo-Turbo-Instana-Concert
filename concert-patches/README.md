# Concert Patches

IBM Concert remediation patches land here. Any push to `concert-patches/` on `main` triggers an automatic rebuild + redeploy.

## Workflow

```
Concert detects CVE → generates patch → commits to concert-patches/ → GitHub Actions triggers
→ apply patches → rebuild images → push to Docker Hub → deploy to K8s → Trivy scan
```

## Supported patch formats

| File | Effect |
|------|--------|
| `*.patch` | Applied via `git apply` |
| `python-base-image.txt` | Overrides Python Dockerfile base image (one line, e.g. `python:3.11-slim-bookworm`) |
| `java-base-image.txt` | Overrides Java Dockerfile base image (one line, e.g. `eclipse-temurin:17-jre`) |
| `requirements-override.txt` | Replaces `python-app/requirements.txt` entirely |
| `pom-versions.json` | JSON map of `groupId:artifactId` to new version |

## Demo: simulate a Concert patch

```bash
# Fix the vulnerable Python base image
echo "python:3.11-slim-bookworm" > concert-patches/python-base-image.txt
git add concert-patches/
git commit -m "Concert: remediate Python base image CVE"
git push origin main
# → GitHub Actions will automatically rebuild with the safe image
```
