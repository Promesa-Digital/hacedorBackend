from rest_framework import serializers

from .models import Article, Author, Category, Event, LibraryPiece, NewsletterSubscriber, Region, Tag, Volume


def _absolute_file_url(field_file, context):
    """URL absoluta de un ImageField/FileField — el frontend hace fetch()
    desde otro origen (puerto 4321 vs 8001), así que una URL relativa no
    sirve. `request` puede faltar de `context` en usos fuera de una vista
    (ej. serialización manual en un test); ahí devolvemos la relativa."""
    if not field_file:
        return ''
    request = context.get('request')
    url = field_file.url
    return request.build_absolute_uri(url) if request else url


class NewsletterSubscriberSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsletterSubscriber
        fields = ['email']

    def create(self, validated_data):
        # get_or_create en vez de un create() plano: la vista ya chequea si
        # el email existe antes de llegar acá, pero esto es la red de
        # seguridad ante una carrera (dos submits casi simultáneos del
        # mismo correo) sin que el segundo reviente con IntegrityError.
        subscriber, _ = NewsletterSubscriber.objects.get_or_create(email=validated_data['email'])
        return subscriber


class RegionSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='pk', read_only=True)
    articleCount = serializers.IntegerField(source='article_count', read_only=True)

    class Meta:
        model = Region
        fields = ['id', 'name', 'code', 'articleCount']


class CategorySerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='pk', read_only=True)
    slug = serializers.SlugField(read_only=True)
    label = serializers.CharField(read_only=True)
    colorVariant = serializers.CharField(source='color_variant', read_only=True)
    featuredVideoUrl = serializers.URLField(source='featured_video_url', read_only=True)
    featuredPodcastUrl = serializers.URLField(source='featured_podcast_url', read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'slug', 'label', 'colorVariant', 'featuredVideoUrl', 'featuredPodcastUrl']


class CategoryAdminSerializer(CategorySerializer):
    """Igual forma que CategorySerializer, pero featuredVideoUrl/
    featuredPodcastUrl son escribibles — slug/label/colorVariant se quedan
    fijos a propósito (atados a una ruta del frontend, ver docstring de
    Category en models.py)."""

    featuredVideoUrl = serializers.URLField(source='featured_video_url', required=False, allow_blank=True)
    featuredPodcastUrl = serializers.URLField(source='featured_podcast_url', required=False, allow_blank=True)

    def validate_featuredVideoUrl(self, value):
        from .embeds import normalize_youtube_embed_url
        normalized = normalize_youtube_embed_url(value)
        if normalized and not normalized.startswith('https://www.youtube.com/embed/'):
            raise serializers.ValidationError('Debe ser una URL válida de YouTube.')
        return normalized

    def validate_featuredPodcastUrl(self, value):
        from .embeds import normalize_spotify_embed_url
        normalized = normalize_spotify_embed_url(value)
        if normalized and not normalized.startswith('https://open.spotify.com/embed/'):
            raise serializers.ValidationError('Debe ser una URL válida de Spotify.')
        return normalized


class AuthorSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='pk', read_only=True)
    avatarUrl = serializers.SerializerMethodField()
    region = serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = ['id', 'name', 'bio', 'avatarUrl', 'region']

    def get_avatarUrl(self, obj):
        return _absolute_file_url(obj.avatar, self.context)

    def get_region(self, obj):
        return obj.region.name if obj.region else None


class AuthorAdminSerializer(AuthorSerializer):
    """Misma forma de lectura que AuthorSerializer, pero con name/bio/region
    escribibles y avatar aceptando upload — usado por el CRUD de autores del
    panel (mismo patrón que ArticleAdminSerializer: PK plano en escritura,
    objeto/string anidado en lectura vía to_representation)."""

    region = serializers.PrimaryKeyRelatedField(queryset=Region.objects.all(), required=False, allow_null=True)
    avatar = serializers.ImageField(write_only=True, required=False, allow_null=True)

    class Meta(AuthorSerializer.Meta):
        fields = AuthorSerializer.Meta.fields + ['avatar']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['region'] = instance.region.name if instance.region else None
        return data


class TagSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='pk', read_only=True)
    usageCount = serializers.IntegerField(source='usage_count', read_only=True)

    class Meta:
        model = Tag
        fields = ['id', 'label', 'slug', 'usageCount']


class VolumeSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='pk', read_only=True)
    author = AuthorSerializer(read_only=True)
    coverImageUrl = serializers.SerializerMethodField()

    class Meta:
        model = Volume
        fields = ['id', 'code', 'title', 'author', 'abstract', 'coverImageUrl']

    def get_coverImageUrl(self, obj):
        return _absolute_file_url(obj.cover_image, self.context)


class ArticleListSerializer(serializers.ModelSerializer):
    """Forma 1:1 con la interfaz Article de lib/types.ts en el frontend."""

    id = serializers.CharField(source='pk', read_only=True)
    category = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    author = AuthorSerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    publishedAt = serializers.DateTimeField(source='published_at', read_only=True)
    readingTimeMinutes = serializers.IntegerField(source='reading_time_minutes', read_only=True)
    coverImageUrl = serializers.SerializerMethodField()
    coverImageOrientation = serializers.CharField(source='cover_image_orientation', read_only=True)
    # Las medidas van al frontend para poder armar una caja con la proporción
    # exacta de un banner y no recortarle el nombre del entrevistado.
    coverImageWidth = serializers.IntegerField(source='cover_image_width', read_only=True)
    coverImageHeight = serializers.IntegerField(source='cover_image_height', read_only=True)
    hasNarration = serializers.BooleanField(source='has_narration', read_only=True)
    narrationAudioUrl = serializers.SerializerMethodField()
    youtubeEmbedUrl = serializers.CharField(source='youtube_embed_url', read_only=True)
    spotifyEmbedUrl = serializers.CharField(source='spotify_embed_url', read_only=True)
    scheduledFor = serializers.DateTimeField(source='scheduled_for', read_only=True)

    class Meta:
        model = Article
        fields = [
            'id', 'slug', 'title', 'excerpt', 'category', 'tags', 'author',
            'publishedAt', 'readingTimeMinutes', 'coverImageUrl', 'coverImageOrientation',
            'coverImageWidth', 'coverImageHeight',
            'hasNarration', 'narrationAudioUrl', 'youtubeEmbedUrl', 'spotifyEmbedUrl',
            'region', 'status', 'scheduledFor',
        ]

    def get_coverImageUrl(self, obj):
        return _absolute_file_url(obj.cover_image, self.context)

    def get_narrationAudioUrl(self, obj):
        return _absolute_file_url(obj.narration_audio, self.context) or None


class ArticleDetailSerializer(ArticleListSerializer):
    class Meta(ArticleListSerializer.Meta):
        fields = ArticleListSerializer.Meta.fields + ['body']


class ArticleAdminSerializer(ArticleDetailSerializer):
    """Igual forma camelCase que el detalle público, pero sin restringir a
    status='published' (getAllArticlesForAdmin) y con los campos que el panel
    necesita editar habilitados para escritura — mismo payload que
    saveDraft()/submitPublication() en lib/publications.ts del frontend.

    coverImage/narrationAudio son write-only: el cliente los manda como
    multipart/form-data (DRF ya trae MultiPartParser en
    DEFAULT_PARSER_CLASSES, no hace falta configurarlo aparte) y la lectura
    sigue siendo coverImageUrl/narrationAudioUrl (heredados, ya absolutos).
    """

    category = serializers.SlugRelatedField(slug_field='slug', queryset=Category.objects.all())
    tags = serializers.SlugRelatedField(slug_field='slug', queryset=Tag.objects.all(), many=True, required=False)
    author = serializers.PrimaryKeyRelatedField(queryset=Author.objects.all())
    region = serializers.PrimaryKeyRelatedField(queryset=Region.objects.all(), required=False, allow_null=True)
    publishedAt = serializers.DateTimeField(source='published_at', required=False)
    scheduledFor = serializers.DateTimeField(source='scheduled_for', required=False, allow_null=True)
    coverImage = serializers.ImageField(source='cover_image', write_only=True, required=False, allow_null=True)
    narrationAudio = serializers.FileField(source='narration_audio', write_only=True, required=False, allow_null=True)
    # ArticleListSerializer los deja read_only (correcto para el detalle
    # público) — acá se sobrescriben a escribibles porque el editor sí
    # necesita poder guardarlos. Bug real que esto corrige: sin este
    # override el "Video de YouTube"/"Podcast de Spotify" del editor nunca
    # se guardaba (DRF ignora en silencio los campos read_only al escribir).
    youtubeEmbedUrl = serializers.CharField(source='youtube_embed_url', required=False, allow_blank=True)
    spotifyEmbedUrl = serializers.CharField(source='spotify_embed_url', required=False, allow_blank=True)
    slug = serializers.SlugField(read_only=True)

    class Meta(ArticleDetailSerializer.Meta):
        fields = ArticleDetailSerializer.Meta.fields + ['coverImage', 'narrationAudio']

    def to_representation(self, instance):
        # Acepta id plano en la escritura (más simple para el <select> del
        # editor) pero devuelve el objeto anidado en la lectura, igual que
        # la API pública — así el panel no necesita un lookup aparte para
        # mostrar el nombre del autor o la región.
        data = super().to_representation(instance)
        data['author'] = AuthorSerializer(instance.author, context=self.context).data
        data['region'] = RegionSerializer(instance.region, context=self.context).data if instance.region else None
        data['tags'] = TagSerializer(instance.tags.all(), many=True, context=self.context).data
        return data

    def create(self, validated_data):
        from django.utils import timezone

        validated_data.setdefault('published_at', timezone.now())
        return super().create(validated_data)

    def validate_youtubeEmbedUrl(self, value):
        from .embeds import normalize_youtube_embed_url
        normalized = normalize_youtube_embed_url(value)
        if normalized and not normalized.startswith('https://www.youtube.com/embed/'):
            raise serializers.ValidationError('Debe ser una URL válida de YouTube.')
        return normalized

    def validate_spotifyEmbedUrl(self, value):
        from .embeds import normalize_spotify_embed_url
        normalized = normalize_spotify_embed_url(value)
        if normalized and not normalized.startswith('https://open.spotify.com/embed/'):
            raise serializers.ValidationError('Debe ser una URL válida de Spotify.')
        return normalized


class EventSerializer(serializers.ModelSerializer):
    """Forma 1:1 con la interfaz EventItem de lib/types.ts en el frontend."""

    id = serializers.CharField(source='pk', read_only=True)
    startsAt = serializers.DateTimeField(source='starts_at', read_only=True)
    coverImageUrl = serializers.SerializerMethodField()
    externalUrl = serializers.URLField(source='external_url', read_only=True)

    class Meta:
        model = Event
        fields = ['id', 'slug', 'title', 'description', 'startsAt', 'location', 'coverImageUrl', 'externalUrl']

    def get_coverImageUrl(self, obj):
        return _absolute_file_url(obj.cover_image, self.context)


class EventAdminSerializer(EventSerializer):
    """Misma forma que el público pero escribible, y con `status` — que el
    endpoint público no expone porque solo devuelve publicados.

    coverImage es write-only y llega como multipart/form-data, igual que en
    ArticleAdminSerializer; la lectura sigue siendo coverImageUrl absoluta.
    """

    startsAt = serializers.DateTimeField(source='starts_at')
    externalUrl = serializers.URLField(source='external_url', required=False, allow_blank=True)
    coverImage = serializers.ImageField(source='cover_image', write_only=True, required=False, allow_null=True)
    slug = serializers.SlugField(read_only=True)

    class Meta(EventSerializer.Meta):
        fields = EventSerializer.Meta.fields + ['status', 'coverImage']


class LibrarySerializer(serializers.ModelSerializer):
    """Forma 1:1 con la interfaz LibraryPiece de lib/types.ts en el frontend."""

    id = serializers.CharField(source='pk', read_only=True)
    author = AuthorSerializer(read_only=True)
    narrator = AuthorSerializer(read_only=True)
    coverImageUrl = serializers.SerializerMethodField()
    audioUrl = serializers.SerializerMethodField()
    sourceNote = serializers.CharField(source='source_note', read_only=True)
    publishedAt = serializers.DateTimeField(source='published_at', read_only=True)

    class Meta:
        model = LibraryPiece
        fields = [
            'id', 'slug', 'title', 'genre', 'body',
            'author', 'narrator', 'coverImageUrl', 'audioUrl', 'sourceNote', 'publishedAt',
        ]

    def get_coverImageUrl(self, obj):
        return _absolute_file_url(obj.cover_image, self.context)

    def get_audioUrl(self, obj):
        return _absolute_file_url(obj.audio, self.context)


class LibraryAdminSerializer(LibrarySerializer):
    """Misma forma de lectura que el público, pero escribible y con `status`.

    author/narrator entran como id plano y salen anidados (igual que
    ArticleAdminSerializer); coverImage y audio son write-only y llegan como
    multipart/form-data, mientras la lectura sigue siendo la URL absoluta.
    """

    author = serializers.PrimaryKeyRelatedField(queryset=Author.objects.all())
    narrator = serializers.PrimaryKeyRelatedField(
        queryset=Author.objects.all(), required=False, allow_null=True
    )
    coverImage = serializers.ImageField(source='cover_image', write_only=True, required=False, allow_null=True)
    audio = serializers.FileField(write_only=True, required=False, allow_null=True)
    sourceNote = serializers.CharField(source='source_note', required=False, allow_blank=True)
    slug = serializers.SlugField(read_only=True)

    class Meta(LibrarySerializer.Meta):
        # `coverImage` y `audio` son los campos de escritura; `coverImageUrl` y
        # `audioUrl` (heredados) los de lectura. Los cuatro tienen que figurar:
        # un campo declarado arriba pero ausente de esta lista lo ignora DRF en
        # silencio, y la subida del audio no llegaría nunca al modelo.
        fields = LibrarySerializer.Meta.fields + ['status', 'coverImage', 'audio']

    def to_representation(self, instance):
        # PrimaryKeyRelatedField devolvería el id pelado; el panel necesita el
        # nombre para llenar la tabla sin un segundo pedido por fila.
        data = super().to_representation(instance)
        data['author'] = AuthorSerializer(instance.author, context=self.context).data
        data['narrator'] = (
            AuthorSerializer(instance.narrator, context=self.context).data if instance.narrator else None
        )
        return data
