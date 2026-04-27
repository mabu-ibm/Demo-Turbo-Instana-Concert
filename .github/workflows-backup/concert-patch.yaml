name: Concert Patch & Rebuild

on:
  push:
    branches: [main]
    paths:
      - 'concert-patches/**'
  pull_request:
    branches: [main]
    paths:
      - 'concert-patches/**'

env:
  PYTHON_IMAGE: mbx1010/load-test-app
  JAVA_IMAGE: mbx1010/vulnerable-echo-service
  K8S_CTX: kubernetes
  NAMESPACE: load-testing

jobs:
  apply-patch-and-rebuild:
    runs-on: self-hosted
    if: github.event_name == 'push'
    steps:
      - uses: actions/checkout@v4

      - name: Apply Concert patches
        run: bash scripts/apply-concert-patch.sh

      - name: Commit patched files
        run: |
          git config user.name "Concert Bot"
          git config user.email "concert-bot@ibm.com"
          if git diff --quiet; then
            echo "No changes from patches"
          else
            git add -A
            git commit -m "Apply Concert remediation patches

          Automated patch from IBM Concert vulnerability workflow"
            git push
          fi

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: mbx1010
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Rebuild & Push Python App
        run: |
          TAG=${GITHUB_SHA::7}
          docker build --no-cache -t $PYTHON_IMAGE:$TAG -t $PYTHON_IMAGE:latest python-app/
          docker push $PYTHON_IMAGE:$TAG
          docker push $PYTHON_IMAGE:latest
          echo "Python digest: $(docker inspect --format='{{index .RepoDigests 0}}' $PYTHON_IMAGE:$TAG)"

      - name: Rebuild & Push Java App
        run: |
          TAG=${GITHUB_SHA::7}
          docker build --no-cache -t $JAVA_IMAGE:$TAG -t $JAVA_IMAGE:latest java-app/
          docker push $JAVA_IMAGE:$TAG
          docker push $JAVA_IMAGE:latest
          echo "Java digest: $(docker inspect --format='{{index .RepoDigests 0}}' $JAVA_IMAGE:$TAG)"

      - name: Deploy to K8s
        run: |
          kubectl --context=$K8S_CTX apply -f k8s/
          kubectl --context=$K8S_CTX -n $NAMESPACE rollout restart deployment/load-test-app
          kubectl --context=$K8S_CTX -n $NAMESPACE rollout restart deployment/vulnerable-echo-service
          kubectl --context=$K8S_CTX -n $NAMESPACE rollout status deployment/load-test-app --timeout=300s
          kubectl --context=$K8S_CTX -n $NAMESPACE rollout status deployment/vulnerable-echo-service --timeout=300s

      - name: Post-deploy Trivy scan
        run: |
          echo "=== Post-remediation vulnerability scan ==="
          trivy k8s --namespace $NAMESPACE --severity CRITICAL --report summary || true
