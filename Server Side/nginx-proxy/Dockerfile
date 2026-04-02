FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
# certbot webroot
RUN mkdir -p /var/www/certbot
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
