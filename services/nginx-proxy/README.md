# Nginx Reverse Proxy for Agent Hub Cloud

Provides subdomain-based routing so each company instance gets its own URL
(`<slug>.agenthub.local`) instead of a raw port number.

## Architecture

```
Browser
  |
  v
Nginx (ports 80/443)
  |
  +-- agenthub.local / control.agenthub.local --> Management Plane (:3000)
  +-- alice.agenthub.local   --> Instance on port 10000
  +-- bob.agenthub.local     --> Instance on port 10001
  +-- (unknown subdomain)    --> 404 JSON response
```

Per-instance configs are written to a shared Docker volume (`nginx-conf`)
by the Management Plane whenever an instance is created or deleted, and
Nginx is hot-reloaded via `nginx -s reload`.

## Local Development Setup

### 1. Generate self-signed wildcard certificate

```bash
bash services/nginx-proxy/generate-certs.sh
```

This creates `services/nginx-proxy/certs/wildcard.{crt,key}` for `*.agenthub.local`.

### 2. Configure local DNS

**Option A — /etc/hosts (manual, per-subdomain):**

```
# Add to /etc/hosts
127.0.0.1  agenthub.local
127.0.0.1  control.agenthub.local
127.0.0.1  alice.agenthub.local
127.0.0.1  bob.agenthub.local
```

**Option B — dnsmasq (automatic wildcard, recommended):**

```bash
# macOS with Homebrew
brew install dnsmasq
echo 'address=/.agenthub.local/127.0.0.1' >> /opt/homebrew/etc/dnsmasq.conf
sudo brew services restart dnsmasq

# Tell macOS to use dnsmasq for .local domains
sudo mkdir -p /etc/resolver
echo 'nameserver 127.0.0.1' | sudo tee /etc/resolver/agenthub.local
```

### 3. Trust the self-signed certificate (optional)

To avoid browser warnings:

```bash
# macOS
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  services/nginx-proxy/certs/wildcard.crt
```

### 4. Start the cloud stack

```bash
# Build frontend first
cd services/management-plane/web && npm run build && cd -

# Start everything
docker compose -f docker-compose.cloud.yml up --build
```

### 5. Access

- Dashboard: https://agenthub.local
- Instance: https://<slug>.agenthub.local

## Custom Domain

Set the `MGMT_DOMAIN` environment variable:

```bash
MGMT_DOMAIN=mycompany.dev docker compose -f docker-compose.cloud.yml up --build
```

Then regenerate certs:

```bash
MGMT_DOMAIN=mycompany.dev bash services/nginx-proxy/generate-certs.sh
```
