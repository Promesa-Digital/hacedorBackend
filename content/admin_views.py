from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.db.models import ProtectedError
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .images import EXTENSIONES, optimizar_bytes
from .models import Article, Author, Category, Event, Region, Tag
from .serializers import (
    ArticleAdminSerializer,
    AuthorAdminSerializer,
    CategoryAdminSerializer,
    EventAdminSerializer,
    RegionSerializer,
    TagSerializer,
)


def _admin_article_queryset():
    return Article.objects.select_related('category', 'author', 'region').prefetch_related('tags').all()


class AdminArticleListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/articles/ — equivalente a getAllArticlesForAdmin()
    (todos los status, no solo published) más creación de publicaciones."""

    serializer_class = ArticleAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None
    queryset = _admin_article_queryset()


class AdminArticleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH /api/admin/articles/<id>/ — "Guardar borrador"/"Programar"/
    "Publicar" del editor son el mismo PATCH con distinto `status` (y
    `scheduledFor` cuando aplica), igual que saveDraft()/submitPublication()
    en lib/publications.ts.

    DELETE es el borrado permanente ("Eliminar definitivamente" en la
    papelera) — solo se permite si el artículo ya está en `trashed`, para
    forzar que siempre pase primero por la papelera y no sea un borrado de
    un clic desde la lista activa."""

    serializer_class = ArticleAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = _admin_article_queryset()

    def perform_destroy(self, instance):
        if instance.status != 'trashed':
            raise ValidationError('Solo se puede eliminar definitivamente un artículo que ya está en la papelera.')
        instance.delete()


class AdminArticleTrashView(APIView):
    """POST /api/admin/articles/<id>/trash/ — equivalente a trashPublication()."""

    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        article = get_object_or_404(Article, pk=pk)
        article.status = 'trashed'
        article.save(update_fields=['status'])
        return Response({'id': str(article.pk), 'status': article.status})


class AdminArticleRestoreView(APIView):
    """POST /api/admin/articles/<id>/restore/ — equivalente a restorePublication().
    Restaura siempre a borrador (no se guarda el status anterior a la
    papelera), consistente con el mismo criterio que ya tenía el frontend."""

    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        article = get_object_or_404(Article, pk=pk)
        article.status = 'draft'
        article.save(update_fields=['status'])
        return Response({'id': str(article.pk), 'status': article.status})


class AdminTagListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/tags/ — equivalente a addCustomTag()."""

    serializer_class = TagSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None
    queryset = Tag.objects.all()

    def create(self, request, *args, **kwargs):
        label = (request.data.get('label') or '').strip()
        if not label:
            return Response({'detail': 'label es requerido.'}, status=status.HTTP_400_BAD_REQUEST)
        tag, _ = Tag.objects.get_or_create(label=label)
        return Response(self.get_serializer(tag).data, status=status.HTTP_201_CREATED)


class AdminTagDeleteView(generics.DestroyAPIView):
    """DELETE /api/admin/tags/<id>/ — equivalente a deleteTag()."""

    permission_classes = [permissions.IsAdminUser]
    queryset = Tag.objects.all()


class AdminAuthorListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/authors/ — el GET puebla el <select> del editor de
    artículos; el POST es la gestión de autores del panel (sección
    "Autores"). Acepta multipart/form-data cuando se sube `avatar`."""

    serializer_class = AuthorAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None
    queryset = Author.objects.all()


class AdminAuthorDeleteView(generics.DestroyAPIView):
    """DELETE /api/admin/authors/<id>/ — a diferencia de Region, Author usa
    on_delete=PROTECT en Article.author y Volume.author (a propósito: no
    queremos que borrar un autor deje huérfano su contenido publicado), así
    que acá sí puede fallar — se traduce a un 400 con mensaje claro en vez
    del 500 que tiraría Django por default."""

    permission_classes = [permissions.IsAdminUser]
    queryset = Author.objects.all()

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': 'No se puede eliminar: este autor tiene publicaciones o volúmenes asociados.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


class AdminRegionListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/regions/ — equivalente a addRegion() en el panel.
    RegionSerializer ya expone name/code como escribibles (solo id y
    articleCount son read_only), y los validators de unicidad de
    Region.name/code los agrega DRF solo por ser ModelSerializer."""

    serializer_class = RegionSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None
    queryset = Region.objects.all()


class AdminRegionDeleteView(generics.DestroyAPIView):
    """DELETE /api/admin/regions/<id>/ — equivalente a deleteRegion().
    Region usa on_delete=SET_NULL en Article/Author, así que borrar una
    región nunca falla por artículos/autores que la referencian: solo
    quedan sin región asignada."""

    permission_classes = [permissions.IsAdminUser]
    queryset = Region.objects.all()


class AdminCategoryListView(generics.ListAPIView):
    """GET /api/admin/categories/ — lista las 4 categorías fijas para la
    sección "Categorías" del panel, donde se edita el video/podcast
    destacado de cada una (label/slug/colorVariant no son editables)."""

    serializer_class = CategoryAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None
    queryset = Category.objects.all()


class AdminCategoryUpdateView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/admin/categories/<slug>/ — solo featuredVideoUrl y
    featuredPodcastUrl son escribibles (CategoryAdminSerializer deja el
    resto read_only). No hay create/delete: las categorías siguen fijas."""

    serializer_class = CategoryAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = Category.objects.all()
    lookup_field = 'slug'


class AdminEventListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/events/ — la agenda completa (incluye borradores,
    a diferencia del endpoint público) y la creación de eventos desde la
    sección "Eventos" del panel. Acepta multipart/form-data cuando se sube
    `coverImage`."""

    serializer_class = EventAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None
    queryset = Event.objects.all()


class AdminEventDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/admin/events/<id>/.

    El borrado es directo, sin papelera: un evento no tiene el peso
    editorial de un artículo (no tiene cuerpo, autor ni historial), así que
    no se justifica el estado `trashed` intermedio que sí tiene Article.
    """

    serializer_class = EventAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = Event.objects.all()


class AdminInlineImageUploadView(APIView):
    """POST /api/admin/media/ — sube una imagen para insertarla DENTRO del
    cuerpo de un artículo, y devuelve su URL absoluta.

    Es distinto de la portada: la portada es un campo del propio Article
    (`coverImage`), mientras que estas imágenes no pertenecen a ninguna fila —
    viven sueltas en disco y el artículo solo las referencia por URL desde su
    markdown. Por eso no hay modelo detrás: crear uno obligaría a limpiar filas
    huérfanas cada vez que alguien borra una imagen del texto.

    Contrapartida asumida: si se quita la imagen del artículo, el archivo queda
    en disco. Es basura barata y recuperable; una fila huérfana apuntando a un
    archivo que ya no existe sería peor.
    """

    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]

    # Solo formatos que un navegador muestra como imagen. SVG queda afuera a
    # propósito: es XML y puede traer <script> adentro, así que subirlo sería
    # abrir un XSS por la puerta de atrás justo en el sitio público.
    ALLOWED_CONTENT_TYPES = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp',
        'image/gif': '.gif',
    }
    MAX_BYTES = 5 * 1024 * 1024

    def post(self, request):
        upload = request.FILES.get('file')
        if not upload:
            raise ValidationError({'file': 'Falta el archivo.'})

        if upload.size > self.MAX_BYTES:
            raise ValidationError(
                {'file': f'La imagen pesa más de {self.MAX_BYTES // (1024 * 1024)} MB.'}
            )

        extension = self.ALLOWED_CONTENT_TYPES.get(upload.content_type)
        if extension is None:
            raise ValidationError({'file': 'Formato no admitido. Se aceptan JPG, PNG, WebP y GIF.'})

        # Se verifica que el archivo SEA una imagen, no que lo diga su
        # content-type: ese lo elige el cliente y se puede mentir. Pillow lo
        # abre de verdad; si no es una imagen, revienta acá y no en el sitio.
        from PIL import Image, UnidentifiedImageError

        try:
            Image.open(upload).verify()
        except (UnidentifiedImageError, OSError):
            raise ValidationError({'file': 'El archivo no es una imagen válida.'})
        finally:
            upload.seek(0)

        # El nombre lo pone el servidor, no el cliente: un nombre de archivo
        # llegado de afuera puede traer barras o ".." e intentar escribir fuera
        # de MEDIA_ROOT. `default_storage.save` además desambigua colisiones.
        import uuid

        # Se achica y reencoda antes de guardar. Estas imágenes se muestran
        # como mucho a 680 px, así que 1600 ya cubre pantallas de alta
        # densidad: subir la foto original sería mandarle megabytes de más a
        # cada lector para mostrarlos a la cuarta parte del tamaño.
        contenido = upload
        optimizada = optimizar_bytes(upload.read(), max_side=1600)
        upload.seek(0)
        if optimizada is not None:
            datos, destino = optimizada
            contenido = ContentFile(datos)
            extension = EXTENSIONES[destino]

        stored = default_storage.save(f'inline/{uuid.uuid4().hex}{extension}', contenido)
        return Response(
            {'url': request.build_absolute_uri(default_storage.url(stored))},
            status=status.HTTP_201_CREATED,
        )
