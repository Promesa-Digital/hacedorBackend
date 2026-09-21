"""
Acorta dos etiquetas de categoría a pedido del cliente.

En la 0006 se habían puesto iguales al nombre de las secciones del sitio
("Crítica Literaria", "Teoría Crítica"). El cliente pidió después los nombres
cortos, y también se renombraron las secciones públicas para que sigan
diciendo lo mismo en los dos lados.

Los `slug` no se tocan: no se ven en ninguna parte y las URLs
(/critica-literaria, /teoria-critica) se mantienen para no romper enlaces ya
compartidos.
"""

from django.db import migrations

ETIQUETAS = {
    'articulos': ('Crítica Literaria', 'Crítica'),
    'revistas': ('Teoría Crítica', 'Teoría'),
}


def acortar(apps, schema_editor):
    Category = apps.get_model('content', 'Category')
    for slug, (_largo, corto) in ETIQUETAS.items():
        Category.objects.filter(slug=slug).update(label=corto)


def revertir(apps, schema_editor):
    Category = apps.get_model('content', 'Category')
    for slug, (largo, _corto) in ETIQUETAS.items():
        Category.objects.filter(slug=slug).update(label=largo)


class Migration(migrations.Migration):
    dependencies = [('content', '0006_etiquetas_de_categoria')]
    operations = [migrations.RunPython(acortar, revertir)]
