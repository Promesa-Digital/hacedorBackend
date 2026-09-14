#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Las 4 categorías están atadas 1:1 a rutas de archivo fijas del frontend
# Astro (/critica-literaria, /entrevistas, /ensayo-y-cronica,
# /teoria-critica → slugs articulos/entrevistas/revistas/ensayos) — no son
# contenido editorial, son estructurales. Sin esto el editor no puede
# guardar ningún artículo (el FK category no existe). Idempotente.
python manage.py shell -c "
from content.models import Category
categories = [
    {'slug': 'articulos', 'label': 'Artículos', 'color_variant': 'primary'},
    {'slug': 'entrevistas', 'label': 'Entrevistas', 'color_variant': 'secondary'},
    {'slug': 'revistas', 'label': 'Revistas', 'color_variant': 'tertiary'},
    {'slug': 'ensayos', 'label': 'Ensayos', 'color_variant': 'secondary'},
]
for c in categories:
    Category.objects.get_or_create(slug=c['slug'], defaults=c)
"

# Crea el usuario admin real si ADMIN_EMAIL/ADMIN_PASSWORD están seteados y
# todavía no existe — idempotente, seguro de correr en cada arranque.
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
  python manage.py shell -c "
from django.contrib.auth.models import User
import os
email = os.environ['ADMIN_EMAIL']
if not User.objects.filter(email=email).exists():
    User.objects.create_superuser(username=email, email=email, password=os.environ['ADMIN_PASSWORD'])
    print(f'Admin creado: {email}')
"
fi

exec gunicorn config.wsgi:application --bind 0.0.0.0:80 --workers 3
