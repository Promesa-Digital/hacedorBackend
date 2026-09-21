"""
Pone las etiquetas de las categorías en sintonía con los nombres de las
secciones públicas.

Las cuatro categorías siempre correspondieron a las cuatro secciones del sitio,
pero se llamaban distinto: el panel ofrecía "Revistas" y eso publicaba en
Teoría Crítica, "Ensayos" publicaba en Ensayo y Crónica, y "Artículos" en
Crítica Literaria. El editor elegía a ciegas.

Los `slug` NO se tocan. No se ven en ninguna parte, y renombrarlos obligaría a
migrar el tipo `CategorySlug` del frontend, las rutas, el mapa de colores y el
parámetro `?category=` de la API, sin ganar nada para quien usa el panel.
"""

from django.db import migrations

ETIQUETAS = {
    'articulos': ('Artículos', 'Crítica Literaria'),
    'revistas': ('Revistas', 'Teoría Crítica'),
    'ensayos': ('Ensayos', 'Ensayo y Crónica'),
}


def renombrar(apps, schema_editor):
    Category = apps.get_model('content', 'Category')
    for slug, (_viejo, nuevo) in ETIQUETAS.items():
        Category.objects.filter(slug=slug).update(label=nuevo)


def revertir(apps, schema_editor):
    Category = apps.get_model('content', 'Category')
    for slug, (viejo, _nuevo) in ETIQUETAS.items():
        Category.objects.filter(slug=slug).update(label=viejo)


class Migration(migrations.Migration):
    dependencies = [('content', '0005_librarypiece')]
    operations = [migrations.RunPython(renombrar, revertir)]
