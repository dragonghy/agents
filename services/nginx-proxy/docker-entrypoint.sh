#!/bin/sh
set -e

# Substitute environment variables in the nginx config template
envsubst '${MGMT_DOMAIN}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# Start nginx in foreground
exec nginx -g 'daemon off;'
