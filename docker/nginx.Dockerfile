FROM nginx:1.27-alpine

COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY app/static /usr/share/nginx/html/static

RUN nginx -t
