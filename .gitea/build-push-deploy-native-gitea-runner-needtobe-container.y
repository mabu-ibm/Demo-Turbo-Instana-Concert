name: Build, Push and Deploy (Native)

on:
  push:
    branches: [main, master]
  workflow_dispatch:

jobs:
  build-push-deploy-native:
    runs-on: ubuntu-latest
    env:
      WORKSPACE_DIR: ${{ github.workspace }}
    steps:
      # Step 1: Checkout code
      - name: Checkout code
        uses: actions/checkout@v4

      # Step 2: Install Docker
      - name: Install Docker
        run: |
          echo "Installing Docker..."
          
          # Detect if we have sudo or running as root
          if command -v sudo &> /dev/null; then
            SUDO="sudo"
          elif [ "$(id -u)" -eq 0 ]; then
            SUDO=""
            echo "Running as root, sudo not needed"
          else
            SUDO=""
            echo "⚠️  Warning: No sudo available and not running as root"
          fi
          
          # Check if Docker is already installed
          if command -v docker &> /dev/null; then
            echo "✓ Docker is already installed"
            docker --version
          else
            echo "Installing Docker from official repository..."
            
            # Detect package manager
            if command -v yum &> /dev/null; then
              PKG_MGR="yum"
            elif command -v apt-get &> /dev/null; then
              PKG_MGR="apt-get"
            elif command -v apk &> /dev/null; then
              PKG_MGR="apk"
            else
              echo "❌ No supported package manager found (yum, apt-get, apk)"
              exit 1
            fi
            
            echo "Using package manager: $PKG_MGR"
            
            # Install based on package manager
            if [ "$PKG_MGR" = "yum" ]; then
              # RHEL/CentOS/AlmaLinux
              $SUDO yum install -y yum-utils device-mapper-persistent-data lvm2
              $SUDO yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
              $SUDO yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
              
            elif [ "$PKG_MGR" = "apt-get" ]; then
              # Debian/Ubuntu - detect which one
              if [ -f /etc/os-release ]; then
                . /etc/os-release
                OS_ID="$ID"
              else
                OS_ID="ubuntu"
              fi
              
              echo "Detected OS: $OS_ID"
              
              # Install prerequisites
              $SUDO apt-get update
              $SUDO apt-get install -y ca-certificates curl gnupg lsb-release
              
              # Create keyrings directory
              $SUDO install -m 0755 -d /etc/apt/keyrings
              
              # Add Docker's official GPG key and repository based on OS
              if [ "$OS_ID" = "debian" ]; then
                # Debian
                curl -fsSL https://download.docker.com/linux/debian/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
                $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
                echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null
              else
                # Ubuntu
                curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
                $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
                echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null
              fi
              
              # Update and install Docker
              $SUDO apt-get update
              $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
              
            elif [ "$PKG_MGR" = "apk" ]; then
              # Alpine Linux
              $SUDO apk add --no-cache docker docker-cli docker-compose
            fi
            
            # Start Docker service (if systemctl available)
            if command -v systemctl &> /dev/null; then
              $SUDO systemctl start docker 2>/dev/null || true
              $SUDO systemctl enable docker 2>/dev/null || true
            fi
            
            # Start Docker daemon if not running (for non-systemd systems)
            if ! pgrep dockerd > /dev/null; then
              if [ -z "$SUDO" ]; then
                dockerd > /dev/null 2>&1 &
              else
                $SUDO dockerd > /dev/null 2>&1 &
              fi
              sleep 3
            fi
            
            # Add current user to docker group (if not root)
            if [ "$(id -u)" -ne 0 ] && [ -n "$SUDO" ]; then
              $SUDO usermod -aG docker $(whoami) 2>/dev/null || true
            fi
            
            # Verify installation
            docker --version
            echo "✓ Docker installed successfully"
          fi
          
          # Ensure Docker socket permissions
          if [ -S /var/run/docker.sock ]; then
            $SUDO chmod 666 /var/run/docker.sock 2>/dev/null || chmod 666 /var/run/docker.sock 2>/dev/null || true
          fi
          
          # Test Docker
          docker info
          echo "✓ Docker is working"

      # Step 3: Install kubectl
      - name: Install kubectl
        run: |
          echo "Installing kubectl..."
          
          # Detect if we have sudo or running as root
          if command -v sudo &> /dev/null; then
            SUDO="sudo"
          elif [ "$(id -u)" -eq 0 ]; then
            SUDO=""
            echo "Running as root, sudo not needed"
          else
            SUDO=""
            echo "⚠️  Warning: No sudo available and not running as root"
          fi
          
          # Check if kubectl is already installed
          if command -v kubectl &> /dev/null; then
            echo "✓ kubectl is already installed"
            kubectl version --client
          else
            echo "Installing kubectl from official repository..."
            
            # Download latest stable kubectl
            curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
            
            # Verify the binary (optional)
            curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
            echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
            
            # Install kubectl
            if [ -n "$SUDO" ]; then
              $SUDO install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
            else
              # If no sudo, try to install to user's local bin or current directory
              if [ -w /usr/local/bin ]; then
                install -m 0755 kubectl /usr/local/bin/kubectl
              elif [ -d "$HOME/.local/bin" ]; then
                mkdir -p "$HOME/.local/bin"
                install -m 0755 kubectl "$HOME/.local/bin/kubectl"
                export PATH="$HOME/.local/bin:$PATH"
              else
                install -m 0755 kubectl ./kubectl
                export PATH="$(pwd):$PATH"
              fi
            fi
            
            # Clean up
            rm -f kubectl.sha256
            
            # Verify installation
            kubectl version --client
            echo "✓ kubectl installed successfully"
          fi

      # Step 4: Verify Docker is available
      - name: Verify Docker
        run: |
          echo "Checking for Docker..."
          echo "Current user: $(whoami)"
          echo "Current groups: $(groups)"
          echo "PATH: $PATH"
          echo ""
          
          # Debug: Check if files exist
          echo "Checking file existence:"
          ls -la /usr/bin/docker 2>&1 || echo "/usr/bin/docker not found"
          ls -la /usr/local/bin/docker 2>&1 || echo "/usr/local/bin/docker not found"
          ls -la /bin/docker 2>&1 || echo "/bin/docker not found"
          echo ""
          
          # Try to find docker using which
          echo "Trying 'which docker':"
          which docker 2>&1 || echo "docker not in PATH"
          echo ""
          
          # Try common Docker locations
          DOCKER_BIN=""
          for path in /usr/bin/docker /usr/local/bin/docker /bin/docker; do
            echo "Checking: $path"
            if [ -f "$path" ]; then
              echo "  File exists: yes"
              if [ -x "$path" ]; then
                echo "  Executable: yes"
                DOCKER_BIN="$path"
                break
              else
                echo "  Executable: no (permissions: $(stat -c '%a' $path 2>/dev/null || stat -f '%p' $path))"
              fi
            else
              echo "  File exists: no"
            fi
          done
          echo ""
          
          if [ -z "$DOCKER_BIN" ]; then
            echo "❌ ERROR: Docker binary not found or not executable!"
            echo ""
            echo "Debug info:"
            echo "  - Check if Docker is installed: rpm -qa | grep docker"
            echo "  - Check Docker service: systemctl status docker"
            echo "  - Check runner user: whoami"
            echo "  - Check runner groups: groups"
            exit 1
          fi
          
          echo "Found Docker at: $DOCKER_BIN"
          $DOCKER_BIN --version
          $DOCKER_BIN info
          echo "✓ Docker is available and working"

      # Step 5: Verify kubectl is available
      - name: Verify kubectl
        run: |
          echo "Checking for kubectl..."
          
          # Try common kubectl locations
          KUBECTL_BIN=""
          for path in /usr/local/bin/kubectl /usr/bin/kubectl /bin/kubectl; do
            if [ -x "$path" ]; then
              KUBECTL_BIN="$path"
              break
            fi
          done
          
          if [ -z "$KUBECTL_BIN" ]; then
            echo "❌ ERROR: kubectl binary not found!"
            echo "Searched locations: /usr/local/bin/kubectl, /usr/bin/kubectl, /bin/kubectl"
            echo ""
            echo "Please install kubectl on the runner host:"
            echo "  curl -LO 'https://dl.k8s.io/release/\$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl'"
            echo "  sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl"
            exit 1
          fi
          
          echo "Found kubectl at: $KUBECTL_BIN"
          $KUBECTL_BIN version --client
          echo "✓ kubectl is available and working"

      # Step 6: Login to Registry
      - name: Login to Gitea Registry
        run: |
          echo "${{ secrets.GIT_TOKEN }}" | docker login ${{ secrets.GIT_REGISTRY }} \
            --username ${{ secrets.GIT_USERNAME }} \
            --password-stdin
          echo "✓ Logged in to registry"

      # Step 7: Build and Push Docker Image
      - name: Build and Push
        run: |
          IMAGE_NAME="${{ secrets.GIT_REGISTRY }}/${{ gitea.repository }}"
          docker build -t ${IMAGE_NAME}:latest -t ${IMAGE_NAME}:${{ gitea.sha }} $WORKSPACE_DIR
          docker push ${IMAGE_NAME}:latest
          docker push ${IMAGE_NAME}:${{ gitea.sha }}
          echo "✓ Image pushed successfully"

      # Step 8: Generate SBOM using Syft
      - name: Generate SBOM with Syft
        run: |
          # Check if syft is installed, if not use container
          if command -v syft &> /dev/null; then
            syft "${{ secrets.GIT_REGISTRY }}/${{ gitea.repository }}:latest" \
              -o spdx-json=$WORKSPACE_DIR/sbom.json \
              -o cyclonedx-json=$WORKSPACE_DIR/sbom-cyclonedx.json
          else
            echo "Syft not installed, using container..."
            docker run --rm \
              --user $(id -u):$(id -g) \
              -v /var/run/docker.sock:/var/run/docker.sock \
              -v "$WORKSPACE_DIR:/output" \
              -w /output \
              anchore/syft:latest \
              "${{ secrets.GIT_REGISTRY }}/${{ gitea.repository }}:latest" \
              -o spdx-json=/output/sbom.json \
              -o cyclonedx-json=/output/sbom-cyclonedx.json
          fi
          
          echo "✓ SBOM generated"
          # Verify SBOM files exist (use test instead of ls for better compatibility)
          if [ -f "$WORKSPACE_DIR/sbom.json" ] && [ -f "$WORKSPACE_DIR/sbom-cyclonedx.json" ]; then
            echo "SBOM files created successfully:"
            echo "  - sbom.json ($(stat -f%z "$WORKSPACE_DIR/sbom.json" 2>/dev/null || stat -c%s "$WORKSPACE_DIR/sbom.json" 2>/dev/null || echo 'unknown') bytes)"
            echo "  - sbom-cyclonedx.json ($(stat -f%z "$WORKSPACE_DIR/sbom-cyclonedx.json" 2>/dev/null || stat -c%s "$WORKSPACE_DIR/sbom-cyclonedx.json" 2>/dev/null || echo 'unknown') bytes)"
          else
            echo "⚠️  Warning: SBOM files may not have been created"
          fi

      # Step 9: Upload SBOM to Concert (Optional)
      - name: Upload SBOM to Concert
        if: secrets.CONCERT_URL != ''
        continue-on-error: true
        env:
          CONCERT_URL: ${{ secrets.CONCERT_URL }}
          CONCERT_API_KEY: ${{ secrets.CONCERT_API_KEY }}
          CONCERT_INSTANCE_ID: ${{ secrets.CONCERT_INSTANCE_ID }}
          CONCERT_APPLICATION_ID: ${{ secrets.CONCERT_APPLICATION_ID }}
        run: |
          pip3 install requests
          python3 $WORKSPACE_DIR/scripts/upload-sbom-to-concert.py $WORKSPACE_DIR/sbom.json --application-id "${CONCERT_APPLICATION_ID}" || echo "⚠ Concert upload skipped"

      # Step 10: Upload SBOM Artifacts
      - name: Upload SBOM Artifacts
        uses: actions/upload-artifact@v3
        with:
          name: sbom-files
          path: |
            sbom.json
            sbom-cyclonedx.json
          retention-days: 90

      # Step 11: Setup kubeconfig
      - name: Setup kubeconfig
        run: |
          mkdir -p $HOME/.kube
          
          # Decode kubeconfig if base64, otherwise use as-is
          if echo "${{ secrets.KUBECONFIG }}" | base64 -d > /dev/null 2>&1; then
            echo "${{ secrets.KUBECONFIG }}" | base64 -d > $HOME/.kube/config
            echo "✓ Decoded base64 kubeconfig"
          else
            echo "${{ secrets.KUBECONFIG }}" > $HOME/.kube/config
            echo "✓ Used plain text kubeconfig"
          fi
          
          chmod 600 $HOME/.kube/config
          
          # Verify kubectl can connect
          kubectl cluster-info
          echo "✓ kubectl configured and connected"

      # Step 12: Deploy Application
      - name: Deploy Application
        run: |
          kubectl apply -f $WORKSPACE_DIR/k8s/deployment.yaml
          kubectl rollout status deployment/hello-world-python -n default --timeout=5m
          echo "✓ Application deployed"

      # Step 13: Create TLS Certificate
      - name: Create TLS Certificate
        run: |
          if kubectl get secret hello-world-python-tls -n default &> /dev/null; then
            echo "✓ TLS secret already exists"
          else
            echo "Creating self-signed TLS certificate..."
            openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
              -keyout $WORKSPACE_DIR/tls.key -out $WORKSPACE_DIR/tls.crt \
              -subj "/CN=hello-world-python.lab.allwaysbeginner.com/O=IBM Bob Secure Development" \
              2>/dev/null
            
            # Create Kubernetes TLS secret
            kubectl create secret tls hello-world-python-tls \
              --cert=$WORKSPACE_DIR/tls.crt \
              --key=$WORKSPACE_DIR/tls.key \
              -n default
            
            rm -f $WORKSPACE_DIR/tls.key $WORKSPACE_DIR/tls.crt
            echo "✓ TLS certificate created"
          fi

      # Step 14: Deploy Secure Ingress
      - name: Deploy Secure Ingress
        run: |
          cat <<'EOFINGRESS' | kubectl apply -f -
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          metadata:
            name: hello-world-python-ingress
            namespace: default
            annotations:
              kubernetes.io/ingress.class: traefik
              traefik.ingress.kubernetes.io/router.tls: "true"
          spec:
            tls:
            - hosts:
              - hello-world-python.lab.allwaysbeginner.com
              secretName: hello-world-python-tls
            rules:
            - host: hello-world-python.lab.allwaysbeginner.com
              http:
                paths:
                - path: /
                  pathType: Prefix
                  backend:
                    service:
                      name: hello-world-python
                      port:
                        number: 80
          EOFINGRESS
          echo "✓ Ingress deployed"

      # Step 15: Apply Permissive Network Policy
      - name: Apply Permissive Network Policy
        run: |
          cat <<'EOFNETPOL' | kubectl apply -f -
          apiVersion: networking.k8s.io/v1
          kind: NetworkPolicy
          metadata:
            name: hello-world-python-netpol
            namespace: default
          spec:
            podSelector:
              matchLabels:
                app: hello-world-python
            policyTypes:
            - Ingress
            - Egress
            ingress:
            - {}
            egress:
            - {}
          EOFNETPOL
          echo "✓ Network policy applied"

      # Step 16: Get Deployment Info
      - name: Get Deployment Info
        run: |
          echo "==================================="
          echo "Deployment Information"
          echo "==================================="
          kubectl get deployment hello-world-python -n default
          kubectl get pods -l app=hello-world-python -n default
          kubectl get service hello-world-python -n default
          kubectl get ingress hello-world-python-ingress -n default
          echo ""
          echo "🔒 Secure Access:"
          echo "  URL: https://hello-world-python.lab.allwaysbeginner.com"
          echo ""
          echo "📋 Add to /etc/hosts on your machine:"
          echo "  <K3S_IP>  hello-world-python.lab.allwaysbeginner.com"
          echo "==================================="

# Made with Bob
