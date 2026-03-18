FROM nginx:alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
RUN mkdir -p /etc/nginx/conf.d /etc/nginx/certs
EXPOSE 80 443
