from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('content.urls')),
    path('api/admin/', include('accounts.urls')),
    path('api/admin/', include('content.admin_urls')),
]

# Archivos subidos desde el panel (portadas, avatares, audio de narración).
#
# Antes esta ruta estaba dentro de un `if settings.DEBUG`, que es lo que sugiere
# la documentación de Django. El resultado en producción era que TODA imagen
# subida por el editor se guardaba bien y después daba 404: el panel la aceptaba,
# la fila en la base quedaba apuntando al archivo, y en la web no se veía nada.
# WhiteNoise, que ya está en el proyecto, solo sirve STATIC_ROOT — no toca
# MEDIA_ROOT.
#
# Servir media desde Django ocupa un worker de gunicorn por cada imagen, así que
# no es la solución definitiva: lo correcto a futuro es un almacenamiento de
# objetos (S3, R2, Spaces) o que nginx sirva el volumen directamente. Para el
# tamaño de esta revista alcanza, y es mejor que no verse.
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
