from django.db.models import ProtectedError
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Article, Author, Category, Region, Tag
from .serializers import ArticleAdminSerializer, AuthorAdminSerializer, CategoryAdminSerializer, RegionSerializer, TagSerializer


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
