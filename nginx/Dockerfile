# Nginx reverse-proxy + SPA server — config only.
# The built frontend (frontend/dist/) is bind-mounted at runtime,
# so you only need to rebuild this image when default.conf changes.
FROM nginx:alpine
COPY default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
