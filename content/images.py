"""
Optimización de las imágenes que suben desde el panel.

Antes no había ninguna: el archivo que subía el editor era exactamente el que
descargaba quien lee. Una foto de celular sin tocar son 8 MB y se muestra a
1180 px — el 71% del ancho viaja para nada, y en datos móviles eso significa
que la nota no termina de abrir.

Hace tres cosas, en este orden:

1. **Aplica la rotación EXIF.** Un celular guarda las fotos verticales en
   horizontal más una marca que dice "rotar 90". El navegador la respeta, pero
   `Image.size` no: un retrato vertical se leía como apaisado y terminaba
   recortado a 21:9. Al hornear la rotación en los píxeles, el archivo queda
   derecho de verdad y las medidas pasan a ser las reales.
2. **Achica** hasta `MAX_SIDE` de lado mayor.
3. **Reencoda** con una calidad razonable.

Es idempotente por construcción: si la imagen ya está por debajo del tope y no
tiene marca de rotación, se devuelve intacta. Por eso puede llamarse en cada
`save()` sin degradar el archivo una y otra vez.
"""

import io
from pathlib import PurePosixPath as Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

# Lado mayor. El lugar más grande del sitio es la portada del artículo, que se
# muestra a 1180 px: 2400 la cubre con margen para pantallas de alta densidad.
MAX_SIDE = 2400

CALIDAD = 82

# Ganancia mínima para justificar reencodar una imagen que ya está dentro
# del tope de tamaño. Ver la explicación en `optimizar_bytes`.
GANANCIA_MINIMA = 0.15

# El GIF queda afuera: puede estar animado y reencodarlo perdería el
# movimiento. En este sitio pesan poco, así que no vale el riesgo.
FORMATOS = {'JPEG', 'PNG', 'WEBP'}

# Etiqueta EXIF de orientación.
_EXIF_ORIENTACION = 274


def _con_transparencia(imagen):
    if imagen.mode in ('RGBA', 'LA'):
        return True
    return imagen.mode == 'P' and 'transparency' in imagen.info


EXTENSIONES = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}


def optimizar_bytes(datos, max_side=MAX_SIDE):
    """Devuelve `(bytes, formato)` optimizados, o None si no hay nada que ganar.

    El formato vuelve porque puede cambiar: casi todo termina en WebP, y
    entonces la extensión del archivo tiene que cambiar con él.

    Nunca levanta: un archivo ilegible no es asunto de esta función (de eso se
    encarga la validación de arriba), así que se deja pasar sin tocar.
    """
    try:
        imagen = Image.open(io.BytesIO(datos))
        imagen.load()
    except Exception:
        return None

    formato = (imagen.format or '').upper()
    if formato not in FORMATOS:
        return None

    rotada = imagen.getexif().get(_EXIF_ORIENTACION, 1) not in (1, None)
    imagen = ImageOps.exif_transpose(imagen)

    ancho, alto = imagen.size
    achicada = max(ancho, alto) > max_side
    if achicada:
        escala = max_side / max(ancho, alto)
        imagen = imagen.resize((round(ancho * escala), round(alto * escala)), Image.LANCZOS)

    # Todo sale en WebP: a igual calidad pesa alrededor de un 30% menos que
    # JPEG, y lo entienden todos los navegadores desde 2020 (Chrome y Android
    # desde mucho antes, Safari desde la 14). Los que no, son teléfonos que ya
    # no reciben actualizaciones.
    destino = 'WEBP'
    salida = io.BytesIO()
    if _con_transparencia(imagen):
        # Con transparencia casi siempre es un logo o una ilustración, no una
        # foto: comprimir sin pérdida evita los halos sucios en los bordes
        # recortados, y aun así pesa bastante menos que el PNG de origen.
        imagen.save(salida, 'WEBP', lossless=True, method=6)
    else:
        imagen.convert('RGB').save(salida, 'WEBP', quality=CALIDAD, method=6)

    nuevo = salida.getvalue()

    # Si se achicó o se rotó hay que reescribir sí o sí: ahí el archivo que
    # está en disco es directamente incorrecto. Si no cambió nada de eso,
    # decide la balanza, y solo se reescribe cuando la ganancia es real.
    #
    # El umbral es lo que hace que esto sea idempotente: reencodar algo ya
    # comprimido da un archivo un poco MÁS chico, así que una comparación
    # simple de tamaños lo daría siempre por bueno y cada edición del artículo
    # degradaría un poco más la portada. Una ganancia por debajo del umbral
    # significa que ya está optimizada y no hay nada que hacerle. Aplica
    # también al pasar a WebP: sobre material ya muy comprimido la conversión
    # puede terminar pesando más que el original.
    if not achicada and not rotada:
        if len(nuevo) > len(datos) * (1 - GANANCIA_MINIMA):
            return None
    return nuevo, destino


def optimizar_imagen(field_file, max_side=MAX_SIDE):
    """Versión para un `ImageField` ya asignado. Reemplaza el contenido del
    campo sin persistir el modelo — de eso se encarga el `save()` que llama."""
    if not field_file:
        return False

    try:
        field_file.open()
        original = field_file.read()
    except (FileNotFoundError, OSError):
        return False

    resultado = optimizar_bytes(original, max_side=max_side)
    if resultado is None:
        field_file.seek(0)
        return False

    datos, destino = resultado
    # Solo el nombre, sin la carpeta: `FieldFile.save()` vuelve a aplicar el
    # `upload_to` del campo, así que pasarle la ruta completa que ya tiene un
    # archivo guardado daría 'articles/articles/foto.webp'.
    #
    # La extensión sigue al formato real: un archivo con bytes WebP y nombre
    # .jpg se serviría con el Content-Type equivocado.
    nombre = Path(field_file.name).with_suffix(EXTENSIONES[destino]).name
    field_file.save(nombre, ContentFile(datos), save=False)
    return True
