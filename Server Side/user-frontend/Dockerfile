FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY static/ /usr/share/nginx/html/
EXPOSE 3001
CMD ["nginx", "-g", "daemon off;"]
