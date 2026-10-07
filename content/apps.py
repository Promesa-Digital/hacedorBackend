from django.apps import AppConfig


class ContentConfig(AppConfig):
    name = 'content'

    def ready(self):
        # Importa las señales que limpian del disco los archivos sin dueño.
        # Va acá y no arriba del módulo: en el momento del import los modelos
        # todavía no están cargados.
        from . import archivos  # noqa: F401
