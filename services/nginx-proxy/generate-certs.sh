#!/bin/bash
# Generate self-signed wildcard certificate for local development.
# Usage: bash services/nginx-proxy/generate-certs.sh
#
# Set MGMT_DOMAIN env var to override the default domain (agenthub.local).

set -euo pipefail

DOMAIN="${MGMT_DOMAIN:-agenthub.local}"
CERT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"

mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "$CERT_DIR/wildcard.key" \
  -out "$CERT_DIR/wildcard.crt" \
  -subj "/CN=*.${DOMAIN}" \
  -addext "subjectAltName=DNS:*.${DOMAIN},DNS:${DOMAIN}"

echo "Generated wildcard cert for *.${DOMAIN} in $CERT_DIR"
