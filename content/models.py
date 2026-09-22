from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from PIL import Image, ImageOps

from .images import optimizar_imagen

from .embeds import normalize_spotify_embed_url, normalize_youtube_embed_url


def _unique_slug(model, value, instance_pk=None):
    """Genera un slug estable con sufijo incremental ante colisiones."""
    max_length = model._meta.get_field('slug').max_length
    base = slugify(value)[:max_length].strip('-') or 'sin-titulo'
    candidate = base
    suffix = 2
    queryset = model.objects.exclude(pk=instance_pk)
    while queryset.filter(slug=candidate).exists():
        tail = f'-{suffix}'
        candidate = f'{base[:max_length - len(tail)].rstrip("-")}{tail}'
        suffix += 1
    return candidate


class Region(models.Model):
    """Región del Perú del Mapa Regional. `code` es el código INEI de dos o
    tres cifras (ej. "040" para Arequipa) usado en las rutas públicas
    (/mapa-regional/<code>) y como filtro de Article/Author."""

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)  # ej. "040"

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def article_count(self):
        return self.articles.filter(status='published').count()


class Author(models.Model):
    """Persona autora de artículos y/o volúmenes. `region` es la región del
    autor (independiente del `region` de cada Article — un autor puede
    escribir sobre una región distinta a la suya)."""

    name = models.CharField(max_length=150)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='authors/', blank=True, null=True)
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True, related_name='authors')

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if self.avatar:
            optimizar_imagen(self.avatar)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Category(models.Model):
    """
    Géneros editoriales (Artículos, Entrevistas, Revistas, Ensayos...).

    El frontend Astro es estático y hoy tiene una ruta de archivo fija por
    categoría (/critica-literaria, /entrevistas, /ensayo-y-cronica...).
    Crear una categoría acá no genera una página nueva sola — requiere
    coordinar con el frontend (ver nota en TagManager/etiquetas-categorias
    del proyecto Astro, donde se dejó explícito que no se puede fingir esto
    del lado del cliente).
    """
    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=100)
    color_variant = models.CharField(
        max_length=20,
        choices=[('primary', 'Primary'), ('secondary', 'Secondary'), ('tertiary', 'Tertiary')],
        default='primary',
        help_text='Debe calzar con CATEGORY_VARIANT_MAP en el frontend (lib/constants.ts).',
    )
    # A diferencia de slug/label/color_variant (fijos, atados a una ruta del
    # frontend), estos dos sí son editables desde el panel — cada sección de
    # archivo (Entrevistas, Crítica Literaria...) elige su propio video/podcast
    # destacado en vez de que se adivine tomando el primer artículo que tenga
    # el campo cargado (eso mezclaba contenido de otras categorías).
    featured_video_url = models.URLField(blank=True)
    featured_podcast_url = models.URLField(blank=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['label']

    def save(self, *args, **kwargs):
        # El panel deja pegar cualquier link de YouTube/Spotify tal cual se
        # copia del navegador (watch?v=, youtu.be, un link normal de
        # open.spotify.com) — normalizarlo acá evita el "refused to
        # connect" que tira un <iframe> con una URL no embebible.
        self.featured_video_url = normalize_youtube_embed_url(self.featured_video_url)
        self.featured_podcast_url = normalize_spotify_embed_url(self.featured_podcast_url)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.label


class Tag(models.Model):
    """Etiqueta libre para clasificar artículos, gestionada desde el panel
    (a diferencia de Category, que es fija). `usage_count` solo cuenta
    artículos publicados, para no inflar el número con borradores."""

    label = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)

    class Meta:
        ordering = ['label']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(type(self), self.label, self.pk)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.label

    @property
    def usage_count(self):
        return self.articles.filter(status='published').count()


class Volume(models.Model):
    """Publicación de la sección Teoría Crítica (una revista/número, no un
    artículo individual) — código editorial tipo "VOL. 04"."""

    code = models.CharField(max_length=20)  # "VOL. 04"
    title = models.CharField(max_length=255)
    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name='volumes')
    abstract = models.TextField()
    cover_image = models.ImageField(upload_to='volumes/', blank=True, null=True)

    class Meta:
        ordering = ['-id']

    def save(self, *args, **kwargs):
        if self.cover_image:
            optimizar_imagen(self.cover_image)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} — {self.title}'


class Event(models.Model):
    """Evento de la agenda pública (presentación, conversatorio, taller).

    A diferencia de Article, no es una pieza editorial: no tiene autor,
    categoría ni etiquetas — lo que importa es cuándo y dónde. `starts_at`
    es el eje: el frontend separa próximos de pasados comparándolo contra
    la fecha actual, así que un evento nunca se "vence" ni hay que borrarlo
    a mano cuando pasa.

    `status` funciona igual que en Article pero con solo dos estados: el
    panel puede dejar un evento armado en `draft` hasta confirmarlo, y el
    endpoint público solo devuelve los `published`.
    """

    STATUS_CHOICES = [
        ('published', 'Publicado'),
        ('draft', 'Borrador'),
    ]

    slug = models.SlugField(unique=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(help_text='Fecha y hora de inicio del evento.')
    location = models.CharField(max_length=255, blank=True, help_text='Ej. "Biblioteca Municipal, Arequipa" o "Transmisión por Zoom".')
    cover_image = models.ImageField(upload_to='events/', blank=True, null=True)
    external_url = models.URLField(blank=True, help_text='Inscripción o más información. Opcional.')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    class Meta:
        ordering = ['-starts_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(type(self), self.title, self.pk)
        if self.cover_image:
            optimizar_imagen(self.cover_image)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} ({self.starts_at:%d/%m/%Y})'


class NewsletterSubscriber(models.Model):
    """Correo suscrito desde el formulario de newsletter del sitio público
    (`Newsletter.astro` → `POST /api/newsletter/`). Sin envío de campañas
    todavía — hoy solo captura la lista."""

    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.email


class Article(models.Model):
    """Pieza editorial (artículo/entrevista/ensayo/crónica). `region` es
    opcional y controla si la pieza aparece en `/mapa-regional/<code>` —
    no tiene por qué coincidir con la región del autor. `slug`,
    `reading_time_minutes` y `cover_image_orientation` se autocalculan en
    `save()`, nunca los mande el cliente."""

    STATUS_CHOICES = [
        ('published', 'Publicado'),
        ('draft', 'Borrador'),
        ('scheduled', 'Programado'),
        ('trashed', 'Eliminado'),
    ]
    ORIENTATION_CHOICES = [
        ('landscape', 'Horizontal'),
        ('portrait', 'Vertical'),
        ('square', 'Cuadrada'),
        ('panoramic', 'Banner'),
    ]

    # A partir de acá una imagen deja de ser una foto apaisada y pasa a ser un
    # banner. Las portadas de las entrevistas son 2400x630 (3.8:1): metidas en
    # la caja 3:2 de una tarjeta se les recortaba el 61% del ancho y el nombre
    # del entrevistado quedaba ilegible ("ERESA RUI" en vez de "TERESA RUIZ").
    # 2.2 deja del lado de "foto" a las panorámicas normales, que sí toleran el
    # recorte porque no tienen texto en los bordes.
    PANORAMIC_RATIO = 2.2

    slug = models.SlugField(unique=True, blank=True)
    title = models.CharField(max_length=255)
    excerpt = models.TextField()
    body = models.TextField(blank=True)

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='articles')
    tags = models.ManyToManyField(Tag, blank=True, related_name='articles')
    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name='articles')
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True, related_name='articles')

    published_at = models.DateTimeField()
    scheduled_for = models.DateTimeField(null=True, blank=True)
    reading_time_minutes = models.PositiveIntegerField(default=1, help_text='Se autocalcula al guardar si se deja en 1.')

    cover_image = models.ImageField(upload_to='articles/', blank=True, null=True)
    cover_image_orientation = models.CharField(max_length=10, choices=ORIENTATION_CHOICES, default='landscape')
    # Las medidas reales, para que el frontend pueda armar una caja con la
    # proporción exacta de un banner y no recortarle nada.
    cover_image_width = models.PositiveIntegerField(null=True, blank=True)
    cover_image_height = models.PositiveIntegerField(null=True, blank=True)

    has_narration = models.BooleanField(default=False)
    narration_audio = models.FileField(upload_to='narration/', blank=True, null=True)
    youtube_embed_url = models.URLField(blank=True)
    spotify_embed_url = models.URLField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    class Meta:
        ordering = ['-published_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(type(self), self.title, self.pk)
        if self.body:
            # readingTimeMinutes es read-only en el serializer — el cliente nunca lo
            # manda, así que siempre se puede recalcular del body actual. Antes solo
            # se recalculaba si valía 1 (el default), lo que lo dejaba congelado para
            # siempre en cuanto el primer cálculo daba otro valor: editar el body de
            # 1000 a 4000 palabras no cambiaba el tiempo de lectura ya guardado.
            word_count = len(self.body.split())
            self.reading_time_minutes = max(1, round(word_count / 200))
        self.has_narration = bool(self.narration_audio)
        # Igual razón que en Category.save(): el editor pega el link tal
        # cual lo copia del navegador, no el formato /embed/ que un <iframe>
        # necesita para no recibir "refused to connect".
        self.youtube_embed_url = normalize_youtube_embed_url(self.youtube_embed_url)
        self.spotify_embed_url = normalize_spotify_embed_url(self.spotify_embed_url)
        if self.cover_image:
            # Achica y reencoda antes de medir: una foto de celular sin tocar
            # son varios MB que viajan enteros a cada lector.
            optimizar_imagen(self.cover_image)
            # Se recalcula en cada save (no solo cuando llega un archivo
            # nuevo) porque cover_image sigue apuntando al mismo archivo en
            # disco en un PATCH sin coverImage — reabrirlo es barato y evita
            # depender de si el campo "cambió" para saber si hay que
            # recalcular.
            try:
                self.cover_image.open()
                with Image.open(self.cover_image) as img:
                    # `exif_transpose` y no `img.size` a secas: un celular
                    # guarda las fotos verticales en horizontal más una marca
                    # EXIF que dice "rotar 90". El navegador la respeta, así
                    # que sin esto un retrato se medía como apaisado y
                    # terminaba recortado a 21:9.
                    width, height = ImageOps.exif_transpose(img).size
                self.cover_image_width = width
                self.cover_image_height = height
                if width / height >= self.PANORAMIC_RATIO:
                    self.cover_image_orientation = 'panoramic'
                elif width > height:
                    self.cover_image_orientation = 'landscape'
                elif height > width:
                    self.cover_image_orientation = 'portrait'
                else:
                    self.cover_image_orientation = 'square'
                self.cover_image.seek(0)
            except (FileNotFoundError, OSError):
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class LibraryPiece(models.Model):
    """Obra literaria ajena — un cuento, un poema o una crónica de otro autor,
    con su narración en audio.

    Deliberadamente NO es una categoría más de Article. Un artículo es la
    crítica que la revista escribe *sobre* la literatura; esto es la literatura
    misma. Si compartieran modelo, un poema de Vallejo saldría en el carrusel
    del inicio y en el RSS como si fuera una nota firmada por El Hacedor.

    `narrator` apunta a Author y no a una tabla aparte: Author ya tiene nombre,
    bio, foto y región, que es justo lo que necesita la ficha de un lector, y
    así la misma persona es una sola fila esté narrando o escribiendo.
    """

    GENRE_CHOICES = [
        ('cuento', 'Cuento'),
        ('poema', 'Poema'),
        ('cronica', 'Crónica'),
    ]
    STATUS_CHOICES = [
        ('published', 'Publicado'),
        ('draft', 'Borrador'),
        ('trashed', 'Eliminado'),
    ]

    slug = models.SlugField(unique=True, blank=True)
    title = models.CharField(max_length=255)
    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name='library_pieces')
    # SET_NULL y no PROTECT: borrar a un narrador no tiene por qué bloquearse
    # por las piezas que leyó — la obra sigue existiendo, se queda sin crédito
    # de voz. Con el autor es al revés, y por eso va PROTECT: una obra sin autor
    # no es nada.
    narrator = models.ForeignKey(
        Author, on_delete=models.SET_NULL, null=True, blank=True, related_name='narrated_pieces'
    )
    genre = models.CharField(max_length=20, choices=GENRE_CHOICES, default='poema')
    body = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to='library/', blank=True, null=True)
    audio = models.FileField(upload_to='library-audio/', blank=True, null=True)
    source_note = models.CharField(
        max_length=255, blank=True, help_text='De dónde sale la pieza. Ej. "de Trilce, 1922".'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # Alfabético y no cronológico: el índice público es A-Z. Ponerlo en el
        # Meta evita tener que acordarse de ordenar en cada consulta.
        ordering = ['title']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(type(self), self.title, self.pk)
        # La fecha se sella sola la primera vez que se publica: es dato de
        # archivo, no algo que el editor tenga que cargar a mano.
        if self.status == 'published' and self.published_at is None:
            self.published_at = timezone.now()
        if self.cover_image:
            optimizar_imagen(self.cover_image)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} — {self.author.name}'
