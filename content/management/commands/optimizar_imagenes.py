"""
Pone al día las imágenes que ya estaban subidas antes de que existiera la
optimización automática.

Las nuevas se achican solas al guardarse (ver `content/images.py`), pero las
que ya están en disco se quedaron como se subieron: fotos de celular enteras
de varios MB que el sitio muestra a 1180 px. Este comando las recorre una vez.

    python manage.py optimizar_imagenes --dry-run   # solo informa
    python manage.py optimizar_imagenes             # aplica

Es seguro correrlo más de una vez: la optimización es idempotente, así que en
la segunda pasada no toca nada.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from content.images import optimizar_imagen
from content.models import Article, Author, Event, Volume

# (modelo, campo). Las imágenes sueltas del cuerpo del artículo ('inline/') no
# están acá: no pertenecen a ninguna fila, solo las referencia el markdown por
# URL, así que renombrarlas rompería los artículos que las usan.
CAMPOS = [
    (Article, 'cover_image'),
    (Author, 'avatar'),
    (Event, 'cover_image'),
    (Volume, 'cover_image'),
]


class Command(BaseCommand):
    help = 'Achica y reencoda a WebP las imágenes ya subidas.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Informa sin escribir nada.')

    def handle(self, *args, **opciones):
        seco = opciones['dry_run']
        antes_total = despues_total = 0
        tocadas = 0

        for modelo, campo in CAMPOS:
            for obj in modelo.objects.exclude(**{campo: ''}).exclude(**{f'{campo}__isnull': True}):
                archivo = getattr(obj, campo)
                try:
                    antes = archivo.size
                    viejo = archivo.name
                except (FileNotFoundError, OSError):
                    self.stderr.write(f'  falta en disco: {modelo.__name__} #{obj.pk} → {archivo.name}')
                    continue

                if seco:
                    # En seco se mide sobre los bytes, sin tocar el campo.
                    from content.images import optimizar_bytes

                    archivo.open()
                    resultado = optimizar_bytes(archivo.read())
                    archivo.seek(0)
                    if resultado is None:
                        continue
                    despues = len(resultado[0])
                else:
                    with transaction.atomic():
                        if not optimizar_imagen(archivo):
                            continue
                        obj.save()
                    obj.refresh_from_db()
                    despues = getattr(obj, campo).size
                    nuevo = getattr(obj, campo).name
                    # El original queda huérfano en cuanto la fila apunta al
                    # archivo nuevo, así que se borra en el mismo paso.
                    if nuevo != viejo:
                        archivo.storage.delete(viejo)

                tocadas += 1
                antes_total += antes
                despues_total += despues
                self.stdout.write(
                    f'  {modelo.__name__} #{obj.pk}: {antes // 1024} KB → {despues // 1024} KB'
                )

        if not tocadas:
            self.stdout.write(self.style.SUCCESS('No hay nada que optimizar.'))
            return

        ahorro = 100 - (despues_total * 100 // antes_total) if antes_total else 0
        prefijo = '[en seco] ' if seco else ''
        self.stdout.write(
            self.style.SUCCESS(
                f'{prefijo}{tocadas} imágenes: '
                f'{antes_total // 1024} KB → {despues_total // 1024} KB ({ahorro}% menos)'
            )
        )
