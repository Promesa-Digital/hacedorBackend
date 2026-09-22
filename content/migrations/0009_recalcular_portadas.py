"""
Recalcula la orientación y guarda las medidas de las portadas que ya estaban.

La 0008 agregó los campos y la detección de banners, pero eso se calcula en
`Article.save()`: los artículos cargados antes siguieron con la orientación
vieja y sin medidas. En la práctica, las portadas de las entrevistas (banners
de 2400x630) se seguían mostrando recortadas después de desplegar.

Va como migración y no como comando para que corra sola al desplegar: si
dependiera de acordarse de ejecutar algo a mano, el sitio quedaría a medias.

Defensiva a propósito: una portada que no se puede abrir se saltea en vez de
voltear el deploy. Perder la orientación de una imagen es un problema estético;
un deploy que no termina es un problema de verdad.
"""

from django.db import migrations

# Mismo valor que Article.PANORAMIC_RATIO. Se repite porque una migración no
# debe depender del modelo actual, que puede cambiar más adelante.
PANORAMIC_RATIO = 2.2


def recalcular(apps, schema_editor):
    from PIL import Image, ImageOps

    Article = apps.get_model('content', 'Article')
    for article in Article.objects.exclude(cover_image='').exclude(cover_image__isnull=True):
        try:
            article.cover_image.open()
            with Image.open(article.cover_image) as img:
                ancho, alto = ImageOps.exif_transpose(img).size
            article.cover_image.close()
        except Exception:
            continue

        if ancho / alto >= PANORAMIC_RATIO:
            orientacion = 'panoramic'
        elif ancho > alto:
            orientacion = 'landscape'
        elif alto > ancho:
            orientacion = 'portrait'
        else:
            orientacion = 'square'

        Article.objects.filter(pk=article.pk).update(
            cover_image_width=ancho, cover_image_height=alto, cover_image_orientation=orientacion
        )


def no_hacer_nada(apps, schema_editor):
    """No se revierte: volver atrás significaría restaurar una orientación mal
    calculada, que es justo lo que esto arregla."""


class Migration(migrations.Migration):
    dependencies = [('content', '0008_article_cover_image_height_article_cover_image_width_and_more')]
    operations = [migrations.RunPython(recalcular, no_hacer_nada)]
