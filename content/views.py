from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from django.utils import timezone

from .models import Article, Author, Category, Event, NewsletterSubscriber, Region, Tag, Volume
from .serializers import (
    ArticleDetailSerializer,
    ArticleListSerializer,
    AuthorSerializer,
    CategorySerializer,
    EventSerializer,
    NewsletterSubscriberSerializer,
    RegionSerializer,
    TagSerializer,
    VolumeSerializer,
)


class ArticlesPagination(PageNumberPagination):
    """{items, total} en vez del {count, next, previous, results} default de
    DRF — es la forma que ya espera getArticles() en lib/api.ts."""

    page_size = 12
    page_size_query_param = 'pageSize'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({'items': data, 'total': self.page.paginator.count})


def _article_base_queryset():
    Article.objects.filter(status='scheduled', scheduled_for__lte=timezone.now()).update(status='published')
    return Article.objects.select_related('category', 'author', 'region').prefetch_related('tags')


def _parse_limit(query_params, default):
    """?limit= no numérico (p.ej. 'abc') reventaba con ValueError sin capturar
    → 500. Se valida acá y se responde 400 en su lugar."""
    raw = query_params.get('limit', default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({'limit': 'Debe ser un número entero.'})
    if not 1 <= value <= 100:
        raise ValidationError({'limit': 'Debe estar entre 1 y 100.'})
    return value


class ArticleListView(generics.ListAPIView):
    """GET /api/articles/?category=&region=&tag=&page=&pageSize= — equivalente a getArticles()."""

    serializer_class = ArticleListSerializer
    pagination_class = ArticlesPagination

    def get_queryset(self):
        qs = _article_base_queryset().filter(status='published')
        category = self.request.query_params.get('category')
        region_code = self.request.query_params.get('region')
        tag_slug = self.request.query_params.get('tag')
        if category:
            qs = qs.filter(category__slug=category)
        if region_code:
            qs = qs.filter(region__code=region_code)
        if tag_slug:
            qs = qs.filter(tags__slug=tag_slug)
        return qs.distinct()


class ArticleDetailView(generics.RetrieveAPIView):
    """GET /api/articles/<slug>/ — equivalente a getArticleBySlug()."""

    serializer_class = ArticleDetailSerializer
    lookup_field = 'slug'
    def get_queryset(self):
        return _article_base_queryset().filter(status='published')


class ArticleFeaturedView(generics.ListAPIView):
    """GET /api/articles/featured/?limit= — equivalente a getFeaturedArticles()."""

    serializer_class = ArticleListSerializer
    pagination_class = None

    def get_queryset(self):
        limit = _parse_limit(self.request.query_params, 5)
        return _article_base_queryset().filter(status='published')[:limit]


class ArticleTrendingView(ArticleFeaturedView):
    """GET /api/articles/trending/?limit= — mismo criterio que featured hoy
    (lib/api.ts tampoco distingue getFeaturedArticles de getTrendingArticles
    todavía: ambas son "las N más recientes publicadas")."""


class ArticleRelatedView(APIView):
    """GET /api/articles/<slug>/related/?limit= — equivalente a getRelatedArticles():
    puntúa por etiquetas en común (x2) + misma categoría (x1)."""

    def get(self, request, slug):
        _article_base_queryset()
        try:
            article = Article.objects.prefetch_related('tags').get(slug=slug, status='published')
        except Article.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        limit = _parse_limit(request.query_params, 3)
        tag_slugs = set(article.tags.values_list('slug', flat=True))

        candidates = _article_base_queryset().filter(status='published').exclude(pk=article.pk)

        scored = []
        for candidate in candidates:
            shared_tags = len(set(t.slug for t in candidate.tags.all()) & tag_slugs)
            same_category = 1 if candidate.category_id == article.category_id else 0
            scored.append((shared_tags * 2 + same_category, candidate))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        related = [candidate for _, candidate in scored[:limit]]
        serializer = ArticleListSerializer(related, many=True, context={'request': request})
        return Response(serializer.data)


class RegionListView(generics.ListAPIView):
    """GET /api/regions/ — equivalente a getRegions()."""

    serializer_class = RegionSerializer
    queryset = Region.objects.all()
    pagination_class = None


class RegionDetailView(generics.RetrieveAPIView):
    """GET /api/regions/<code>/ — equivalente a getRegionByCode()."""

    serializer_class = RegionSerializer
    queryset = Region.objects.all()
    lookup_field = 'code'


class RegionAuthorsView(generics.ListAPIView):
    """GET /api/regions/<code>/authors/ — equivalente a getAuthorsByRegion()."""

    serializer_class = AuthorSerializer
    pagination_class = None

    def get_queryset(self):
        return Author.objects.filter(region__code=self.kwargs['code'])


class VolumeListView(generics.ListAPIView):
    """GET /api/volumes/ — equivalente a getVolumes()."""

    serializer_class = VolumeSerializer
    queryset = Volume.objects.select_related('author').all()
    pagination_class = None


class TagListView(generics.ListAPIView):
    """GET /api/tags/ — equivalente a getTags(), ordenadas por uso descendente."""

    serializer_class = TagSerializer
    pagination_class = None

    def get_queryset(self):
        return sorted(Tag.objects.all(), key=lambda t: t.usage_count, reverse=True)


class TagDetailView(generics.RetrieveAPIView):
    """GET /api/tags/<slug>/ — equivalente a getTagBySlug()."""

    serializer_class = TagSerializer
    queryset = Tag.objects.all()
    lookup_field = 'slug'


class CategoryListView(generics.ListAPIView):
    """GET /api/categories/ — equivalente a getCategories(). Trae, entre
    otros, featuredVideoUrl/featuredPodcastUrl que cada página de archivo usa
    para su widget "Video/Podcast destacado" (elegido a mano desde el panel,
    no adivinado a partir de artículos)."""

    serializer_class = CategorySerializer
    queryset = Category.objects.all()
    pagination_class = None


class CategoryDetailView(generics.RetrieveAPIView):
    """GET /api/categories/<slug>/ — equivalente a getCategoryBySlug()."""

    serializer_class = CategorySerializer
    queryset = Category.objects.all()
    lookup_field = 'slug'


class NewsletterSubscribeView(APIView):
    """POST /api/newsletter/ {email} — público, sin auth. Suscribirse dos
    veces con el mismo correo no es un error para quien lo usa (UX), aunque
    `email` sea unique=True: se responde 200 igual en vez de dejar que el
    UniqueValidator del serializer lo rechace como 400."""

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        if NewsletterSubscriber.objects.filter(email=email).exists():
            return Response({'email': email, 'alreadySubscribed': True})

        serializer = NewsletterSubscriberSerializer(data={'email': email})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'newsletter'


class EventListView(generics.ListAPIView):
    """GET /api/events/ — agenda pública, equivalente a getEvents().

    Solo devuelve publicados; los borradores quedan para el panel. El orden
    es `-starts_at` (heredado del Meta del modelo), así que el frontend
    recibe primero lo más cercano en el futuro y separa próximos de pasados
    comparando contra la fecha actual.
    """

    serializer_class = EventSerializer
    queryset = Event.objects.filter(status='published')
    pagination_class = None
