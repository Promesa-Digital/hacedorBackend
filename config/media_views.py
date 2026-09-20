"""
Entrega de archivos subidos con soporte de peticiones por tramo (HTTP Range).

Por qué existe este archivo en vez de usar `django.views.static.serve` a secas:
Django 6 no implementa Range en ninguna parte —ni en `FileResponse` ni en
`serve`—, así que devolvía siempre `200 OK` con el archivo entero. Para un JPG da
igual, pero un reproductor de audio o de video adelanta pidiendo un tramo de
bytes: al recibir todo desde el principio, la barra de progreso no se puede
mover. En la práctica, la narración de los artículos no se podía adelantar ni
retroceder.

Se apoya en `serve` para lo importante —resolver la ruta sin dejar salir de
MEDIA_ROOT, el 404 y el tipo de contenido— y solo agrega el tramo encima.
"""

import re

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views.static import serve

# `bytes=0-1023`, `bytes=1024-` (de ahí al final) o `bytes=-500` (los últimos 500).
RANGE_RE = re.compile(r'^bytes=(\d*)-(\d*)$')

# Tamaño de lectura. Ni tan chico que haga miles de vueltas ni tan grande que se
# cargue medio archivo en memoria de una.
CHUNK = 64 * 1024


def _leer_tramo(archivo, largo):
    """Lee como máximo `largo` bytes. Hace falta porque `FileResponse` sobre un
    archivo ya posicionado seguiría leyendo hasta el final, y un tramo tiene que
    cortar donde dice el encabezado."""
    restante = largo
    while restante > 0:
        datos = archivo.read(min(CHUNK, restante))
        if not datos:
            break
        restante -= len(datos)
        yield datos


def serve_media(request, path):
    respuesta = serve(request, path, document_root=settings.MEDIA_ROOT)

    # Avisar que se aceptan tramos: sin esto el navegador ni lo intenta y
    # deshabilita la barra de progreso.
    respuesta.headers['Accept-Ranges'] = 'bytes'

    cabecera = request.headers.get('Range')
    if not cabecera or respuesta.status_code != 200:
        return respuesta

    coincidencia = RANGE_RE.match(cabecera.strip())
    if not coincidencia:
        # Un Range que no se entiende se puede ignorar y mandar todo: es
        # respuesta válida y mejor que fallar.
        return respuesta

    total = int(respuesta.headers['Content-Length'])
    desde_txt, hasta_txt = coincidencia.groups()

    if desde_txt == '' and hasta_txt == '':
        return respuesta
    if desde_txt == '':
        # `bytes=-500`: los últimos 500 bytes.
        largo = int(hasta_txt)
        desde = max(total - largo, 0)
        hasta = total - 1
    else:
        desde = int(desde_txt)
        hasta = int(hasta_txt) if hasta_txt else total - 1

    hasta = min(hasta, total - 1)

    if desde > hasta or desde >= total:
        respuesta.close()
        fuera = HttpResponse(status=416)
        fuera['Content-Range'] = f'bytes */{total}'
        fuera['Accept-Ranges'] = 'bytes'
        return fuera

    archivo = respuesta.file_to_stream
    archivo.seek(desde)
    largo = hasta - desde + 1

    parcial = FileResponse(
        _leer_tramo(archivo, largo),
        status=206,
        content_type=respuesta.headers['Content-Type'],
    )
    parcial['Content-Range'] = f'bytes {desde}-{hasta}/{total}'
    parcial['Content-Length'] = str(largo)
    parcial['Accept-Ranges'] = 'bytes'
    return parcial
