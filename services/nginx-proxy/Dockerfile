FROM nginx:alpine
# Put template in a custom location (NOT /etc/nginx/templates/ which auto-writes to conf.d)
COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY docker-entrypoint.sh /docker-entrypoint-custom.sh
RUN chmod +x /docker-entrypoint-custom.sh && \
    mkdir -p /etc/nginx/conf.d /etc/nginx/certs && \
    rm -f /etc/nginx/conf.d/default.conf
EXPOSE 80 443
ENTRYPOINT ["/docker-entrypoint-custom.sh"]
