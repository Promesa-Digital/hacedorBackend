"""
Limpieza de archivos subidos que dejan de tener dueño.

Django NO borra del disco el archivo de un `FileField`: ni cuando se elimina el
registro, ni cuando se reemplaza por otro. Es deliberado de su parte —una
transacción puede revertirse y el archivo ya no estaría—, pero el efecto es que
el almacenamiento solo crece.

Se midió en producción: ocho archivos sin dueño en las primeras semanas de uso.
Pocos, pero la cuenta nunca baja, y el 96 % del disco de este proyecto es audio
de narraciones de decenas de megas cada uno. Una obra de Biblioteca a la que se
le reemplaza la voz deja el audio viejo ocupando lugar para siempre.

Dos momentos, dos señales:

- `post_delete`: se borró el registro, sus archivos ya no los usa nadie.
- `pre_save`: se está por reemplazar un archivo; el anterior queda sin dueño.

Ambos borran DESPUÉS de que la transacción confirme (`on_commit`). Si se
borrara antes y la transacción se revirtiera, quedaría un registro apuntando a
un archivo inexistente: un agujero peor que el que se quería tapar.
"""

from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import Article, Author, Event, LibraryPiece, Region, Volume

# Qué campo de archivo tiene cada modelo. Si mañana se agrega uno nuevo y no se
# suma acá, sus archivos empiezan a acumularse en silencio: hay una prueba que
# recorre los modelos y falla si alguno queda afuera.
CAMPOS_DE_ARCHIVO = {
    Region: ('image',),
    Author: ('avatar',),
    Volume: ('cover_image',),
    Event: ('cover_image',),
    Article: ('cover_image', 'narration_audio'),
    LibraryPiece: ('cover_image', 'audio'),
}


def _borrar_del_disco(campo):
    """Borra el archivo sin tocar el registro.

    El `save=False` es el punto: `FieldFile.delete()` guardaría el modelo, y acá
    el modelo o bien ya no existe, o bien está a mitad de su propio guardado.
    """
    if not campo:
        return
    try:
        campo.delete(save=False)
    except Exception:  # noqa: BLE001
        # Un archivo que no se pudo borrar es un residuo; una excepción acá
        # sería un borrado o un guardado fallido de cara al editor. El residuo
        # es el mal menor.
        pass


@receiver(post_delete)
def limpiar_al_borrar(sender, instance, **kwargs):
    campos = CAMPOS_DE_ARCHIVO.get(sender)
    if not campos:
        return
    archivos = [getattr(instance, nombre) for nombre in campos]
    transaction.on_commit(lambda: [_borrar_del_disco(a) for a in archivos])


@receiver(pre_save)
def limpiar_al_reemplazar(sender, instance, **kwargs):
    campos = CAMPOS_DE_ARCHIVO.get(sender)
    if not campos or not instance.pk:
        return

    try:
        anterior = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        # Alta con la clave puesta a mano: no hay nada anterior que limpiar.
        return

    reemplazados = []
    for nombre in campos:
        viejo = getattr(anterior, nombre)
        nuevo = getattr(instance, nombre)
        # Se compara el NOMBRE y no el objeto: dos `FieldFile` distintos pueden
        # apuntar al mismo archivo, y borrarlo dejaría al registro sin él.
        if viejo and viejo.name != getattr(nuevo, 'name', None):
            reemplazados.append(viejo)

    if reemplazados:
        transaction.on_commit(lambda: [_borrar_del_disco(a) for a in reemplazados])
