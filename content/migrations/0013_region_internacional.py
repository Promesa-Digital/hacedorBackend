"""
Crea la región "Internacional" (autores que escriben desde fuera del Perú).

Va como migración de datos y no como un alta a mano en el panel para que
exista igual en local, en las pruebas y en producción: si dependiera de que
alguien la cree desde el panel de cada entorno, el deploy dejaría el
desplegable de región sin la opción que el cliente pidió, o con el nombre y el
código escritos distinto en cada base — y el código es parte de la URL
pública, así que un dedazo ahí rompe enlaces.

Trae también el ensanche de `Region.code` a 20 caracteres, porque "internacional"
no entra en los 10 que había. Van juntas a propósito: la fila nueva no se puede
insertar antes de que la columna la acepte.
"""

from django.db import migrations, models

# Mismo valor que Region.CODE_INTERNACIONAL. Se repite en vez de importarlo
# porque una migración no debe depender del modelo actual, que puede cambiar
# más adelante (es el mismo criterio de la 0009 con PANORAMIC_RATIO).
CODE_INTERNACIONAL = 'internacional'
NOMBRE_INTERNACIONAL = 'Internacional'


def crear_internacional(apps, schema_editor):
    """Idempotente: se apoya en get_or_create sobre `code`, que es único.

    Correrla dos veces no duplica ni revienta, y tampoco pisa el nombre si
    alguien lo ajustó desde el panel — la región ya creada se deja como está.
    """
    Region = apps.get_model('content', 'Region')
    Region.objects.get_or_create(code=CODE_INTERNACIONAL, defaults={'name': NOMBRE_INTERNACIONAL})


def borrar_internacional(apps, schema_editor):
    """La reversa saca la región, no los artículos.

    Article.region y Author.region usan on_delete=SET_NULL, así que al volver
    atrás las publicaciones internacionales quedan sin región asignada en vez
    de desaparecer. Es la pérdida mínima y recuperable: volver a aplicar la
    migración recrea la región, y basta reasignarla desde el panel.

    Se filtra por `code` y no por `name` porque el código es lo único que esta
    migración garantiza haber escrito.
    """
    Region = apps.get_model('content', 'Region')
    Region.objects.filter(code=CODE_INTERNACIONAL).delete()


class Migration(migrations.Migration):
    dependencies = [('content', '0012_article_drop_cap_librarypiece_drop_cap')]
    operations = [
        migrations.AlterField(
            model_name='region',
            name='code',
            field=models.CharField(max_length=20, unique=True),
        ),
        migrations.RunPython(crear_internacional, borrar_internacional),
    ]
