# Biblioteca (Fase 1) — Plan de implementación

> **Para quien ejecute:** las tareas van en orden; cada una termina con su ciclo de
> pruebas y un commit. Los pasos usan `- [ ]` para ir marcándolos.

> **Regla del proyecto:** los bloques `git` de este plan son **texto para que los
> corra la persona**. El agente no ejecuta comandos git por su cuenta.

**Objetivo:** que El Hacedor pueda cargar cuentos, poemas y crónicas con su portada y
su narración desde el panel, y que se vean en un índice alfabético público.

**Arquitectura:** modelo propio `LibraryPiece` en Django, separado de `Article`.
API pública de solo lectura + API de admin con CRUD. En Astro, dos páginas de panel
(listado + editor) y dos públicas (índice + pieza). Se reusa todo lo que ya existe:
`AudioPlayer`, `FileField`, `RichTextEditor`, la optimización de imágenes y el proxy
autenticado.

**Stack:** Django 6 + DRF + Pillow (backend) · Astro 7 + marked + sanitize-html + vitest (frontend)

**Especificación:** `backend/docs/specs/2026-09-21-biblioteca-design.md`

## Restricciones globales

- Repos separados: `backend/` y `frontend/` son dos repos git distintos. Cada commit
  va en el suyo.
- Python del backend: usar siempre `.venv/bin/python`, nunca `python` pelado.
- Identificadores y nombres de archivo en inglés. Comentarios, textos de interfaz y
  mensajes de error en español neutro (convención vigente del proyecto).
- Serializers en camelCase hacia el frontend, snake_case en el modelo.
- No usar `cat`, `grep`, `find`, `sed`, `ls`. Usar `bat`, `rg`, `fd`, `sd`, `eza`.
- El backend tiene trabajo sin commitear de una sesión anterior (optimización de
  imágenes, bug de EXIF, tests). **Nunca usar `git add .`**: agregar archivo por
  archivo, como muestra cada tarea.
- Estados de la pieza: `draft` / `published` / `trashed`. La papelera se maneja con
  `PATCH {status}`, no con endpoints dedicados.

---

### Task 1: Modelo `LibraryPiece` y migración

**Archivos:**
- Modificar: `backend/content/models.py` (agregar al final, antes de nada más)
- Modificar: `backend/content/tests.py` (agregar al final)
- Crear: `backend/content/migrations/000X_librarypiece.py` (lo genera Django)

**Interfaces:**
- Consume: `_unique_slug` (`models.py:10`), `optimizar_imagen` (`content/images.py`)
- Produce: `LibraryPiece` con campos `title`, `slug`, `author`, `narrator`, `genre`,
  `body`, `cover_image`, `audio`, `source_note`, `status`, `published_at`.
  `GENRE_CHOICES` y `STATUS_CHOICES` como atributos de clase.

- [ ] **Paso 1: Escribir las pruebas que fallan**

Agregar al final de `backend/content/tests.py`:

```python
class LibraryPieceModelTests(AdminAPITestCase):
    def _pieza(self, **extra):
        datos = {'title': 'Masa', 'author': self.author, 'genre': 'poema', 'body': 'verso'}
        datos.update(extra)
        return LibraryPiece.objects.create(**datos)

    def test_genera_el_slug(self):
        self.assertEqual(self._pieza().slug, 'masa')

    def test_el_slug_no_choca(self):
        self._pieza()
        self.assertEqual(self._pieza().slug, 'masa-2')

    def test_ordena_alfabeticamente_no_por_fecha(self):
        # El índice público es A-Z; si el orden fuera por id, "Trilce" iría primero
        # solo por haberse cargado antes.
        self._pieza(title='Trilce')
        self._pieza(title='Masa')
        self.assertEqual([p.title for p in LibraryPiece.objects.all()], ['Masa', 'Trilce'])

    def test_borrar_al_narrador_no_borra_la_pieza(self):
        narrador = Author.objects.create(name='Bruno Odar')
        pieza = self._pieza(narrator=narrador)
        narrador.delete()
        pieza.refresh_from_db()
        self.assertIsNone(pieza.narrator)

    def test_no_deja_borrar_al_autor_con_piezas(self):
        from django.db.models import ProtectedError

        self._pieza()
        with self.assertRaises(ProtectedError):
            self.author.delete()

    def test_optimiza_la_portada(self):
        pieza = self._pieza(
            cover_image=SimpleUploadedFile('tapa.jpg', _imagen_bytes(4000, 3000), content_type='image/jpeg')
        )
        pieza.refresh_from_db()
        with Image.open(pieza.cover_image) as img:
            self.assertEqual(max(img.size), 2400)

    def test_al_publicar_se_sella_la_fecha(self):
        pieza = self._pieza(status='published')
        self.assertIsNotNone(pieza.published_at)

    def test_un_borrador_no_tiene_fecha(self):
        self.assertIsNone(self._pieza().published_at)
```

Agregar `LibraryPiece` al import de modelos que ya existe en `tests.py:14`:

```python
from .models import Article, Author, Category, Event, LibraryPiece, NewsletterSubscriber, Region, Tag
```

- [ ] **Paso 2: Correr y verificar que fallan**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend
.venv/bin/python manage.py test content.tests.LibraryPieceModelTests 2>&1 | tail -20
```

Esperado: `ImportError: cannot import name 'LibraryPiece'`.

- [ ] **Paso 3: Escribir el modelo**

Agregar al final de `backend/content/models.py`:

```python
class LibraryPiece(models.Model):
    """Obra literaria ajena — un cuento, un poema o una crónica de otro autor,
    con su narración en audio.

    Deliberadamente NO es una categoría más de Article. Un artículo es la
    crítica que la revista escribe *sobre* la literatura; esto es la
    literatura misma. Si compartieran modelo, un poema de Vallejo saldría en
    el carrusel del inicio y en el RSS como si fuera una nota firmada por El
    Hacedor.

    `narrator` apunta a Author, no a una tabla aparte: Author ya tiene nombre,
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
    # por las piezas que leyó. La obra sigue existiendo, se queda sin crédito
    # de voz. Con el autor es al revés: una obra sin autor no es nada.
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
        # Alfabético, no cronológico: el índice público es A-Z. Ponerlo acá
        # evita tener que acordarse de ordenar en cada consulta.
        ordering = ['title']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(type(self), self.title, self.pk)
        # La fecha se sella sola la primera vez que se publica. Es dato de
        # archivo, no algo que El Hacedor tenga que cargar a mano.
        if self.status == 'published' and self.published_at is None:
            self.published_at = timezone.now()
        if self.cover_image:
            optimizar_imagen(self.cover_image)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} — {self.author.name}'
```

Agregar el import de `timezone` arriba del todo en `models.py`, junto a los otros
imports de Django:

```python
from django.utils import timezone
```

- [ ] **Paso 4: Generar y aplicar la migración**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend
.venv/bin/python manage.py makemigrations content
.venv/bin/python manage.py migrate
```

Esperado: `Create model LibraryPiece` y luego `Applying content.00XX... OK`.

- [ ] **Paso 5: Correr y verificar que pasan**

```bash
.venv/bin/python manage.py test content.tests.LibraryPieceModelTests 2>&1 | rg "^(OK|Ran |FAILED)"
```

Esperado: `OK`, 8 pruebas.

- [ ] **Paso 6: Correr la suite entera, para no romper nada**

```bash
.venv/bin/python manage.py test content 2>&1 | rg "^(OK|Ran |FAILED)"
```

Esperado: `OK`.

- [ ] **Paso 7: Commit** (lo corre la persona)

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend
git add content/models.py content/tests.py content/migrations/
git commit -m "feat(biblioteca): modelo LibraryPiece"
```

---

### Task 2: API pública de la Biblioteca

**Archivos:**
- Modificar: `backend/content/serializers.py`
- Modificar: `backend/content/views.py`
- Modificar: `backend/content/urls.py`
- Modificar: `backend/content/tests.py`

**Interfaces:**
- Consume: `LibraryPiece` (Task 1), `_absolute_file_url` (`serializers.py:6`),
  `AuthorSerializer` (`serializers.py:~80`)
- Produce: `LibrarySerializer` con campos
  `id, slug, title, genre, body, author, narrator, coverImageUrl, audioUrl, sourceNote, publishedAt`;
  rutas `GET /api/library/` y `GET /api/library/<slug>/`

- [ ] **Paso 1: Escribir las pruebas que fallan**

Agregar al final de `backend/content/tests.py`:

```python
class LibraryPublicAPITests(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Arequipa', code='040')
        self.author = Author.objects.create(name='César Vallejo', region=self.region)
        self.narrator = Author.objects.create(name='Bruno Odar')
        LibraryPiece.objects.create(
            title='Masa', author=self.author, narrator=self.narrator,
            genre='poema', body='verso', status='published',
        )
        LibraryPiece.objects.create(title='Paco Yunque', author=self.author, genre='cuento', status='published')
        LibraryPiece.objects.create(title='Sin publicar', author=self.author, genre='poema', status='draft')

    def test_solo_devuelve_publicadas(self):
        response = self.client.get('/api/library/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({p['title'] for p in response.data}, {'Masa', 'Paco Yunque'})

    def test_viene_ordenado_alfabeticamente(self):
        self.assertEqual([p['title'] for p in self.client.get('/api/library/').data], ['Masa', 'Paco Yunque'])

    def test_filtra_por_genero(self):
        response = self.client.get('/api/library/?genre=cuento')
        self.assertEqual([p['title'] for p in response.data], ['Paco Yunque'])

    def test_un_genero_que_no_existe_no_revienta(self):
        self.assertEqual(self.client.get('/api/library/?genre=haiku').data, [])

    def test_trae_autor_y_narrador_anidados(self):
        pieza = next(p for p in self.client.get('/api/library/').data if p['title'] == 'Masa')
        self.assertEqual(pieza['author']['name'], 'César Vallejo')
        self.assertEqual(pieza['narrator']['name'], 'Bruno Odar')

    def test_sin_narrador_devuelve_null(self):
        pieza = next(p for p in self.client.get('/api/library/').data if p['title'] == 'Paco Yunque')
        self.assertIsNone(pieza['narrator'])

    def test_detalle_por_slug(self):
        response = self.client.get('/api/library/masa/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['body'], 'verso')

    def test_el_detalle_de_un_borrador_da_404(self):
        response = self.client.get('/api/library/sin-publicar/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
```

- [ ] **Paso 2: Correr y verificar que fallan**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend
.venv/bin/python manage.py test content.tests.LibraryPublicAPITests 2>&1 | tail -15
```

Esperado: 404 en todas — la ruta no existe todavía.

- [ ] **Paso 3: Escribir el serializer**

Agregar al final de `backend/content/serializers.py`:

```python
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
```

Agregar `LibraryPiece` al import de modelos al inicio de `serializers.py`.

- [ ] **Paso 4: Escribir las vistas**

Agregar al final de `backend/content/views.py`:

```python
class LibraryListView(generics.ListAPIView):
    """GET /api/library/?genre= — el índice de la Biblioteca.

    Sin paginar y devolviendo todo: el índice alfabético del frontend agrupa
    por la primera letra del título, y hacerlo en el cliente con una sola
    respuesta es más barato que 27 pedidos, uno por letra.
    """

    serializer_class = LibrarySerializer
    pagination_class = None

    def get_queryset(self):
        queryset = LibraryPiece.objects.filter(status='published').select_related('author', 'narrator')
        genre = self.request.query_params.get('genre')
        # Un género inventado devuelve vacío, no un 400: el filtro llega de un
        # parámetro de URL que cualquiera puede escribir a mano.
        return queryset.filter(genre=genre) if genre else queryset


class LibraryDetailView(generics.RetrieveAPIView):
    """GET /api/library/<slug>/ — una pieza."""

    serializer_class = LibrarySerializer
    lookup_field = 'slug'
    queryset = LibraryPiece.objects.filter(status='published').select_related('author', 'narrator')
```

Agregar `LibraryPiece` al import de modelos (`views.py:9`) y `LibrarySerializer` al de
serializers (`views.py:10-20`).

- [ ] **Paso 5: Registrar las rutas**

En `backend/content/urls.py`, agregar antes de la línea de `newsletter/`:

```python
    path('library/', views.LibraryListView.as_view(), name='library-list'),
    path('library/<slug:slug>/', views.LibraryDetailView.as_view(), name='library-detail'),
```

- [ ] **Paso 6: Correr y verificar que pasan**

```bash
.venv/bin/python manage.py test content.tests.LibraryPublicAPITests 2>&1 | rg "^(OK|Ran |FAILED)"
```

Esperado: `OK`, 8 pruebas.

- [ ] **Paso 7: Commit** (lo corre la persona)

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend
git add content/serializers.py content/views.py content/urls.py content/tests.py
git commit -m "feat(biblioteca): API pública de lectura"
```

---

### Task 3: API de admin

**Archivos:**
- Modificar: `backend/content/serializers.py`
- Modificar: `backend/content/admin_views.py`
- Modificar: `backend/content/admin_urls.py`
- Modificar: `backend/content/tests.py`

**Interfaces:**
- Consume: `LibrarySerializer` (Task 2)
- Produce: `LibraryAdminSerializer` (acepta `author`, `narrator` como ids;
  `coverImage`, `audio` write-only; `status` y `sourceNote` escribibles);
  `AdminLibraryListCreateView`, `AdminLibraryDetailView`;
  rutas `/api/admin/library/` y `/api/admin/library/<pk>/`

- [ ] **Paso 1: Escribir las pruebas que fallan**

Agregar al final de `backend/content/tests.py`:

```python
class LibraryAdminTests(AdminAPITestCase):
    def _crear(self, **extra):
        datos = {'title': 'Masa', 'author': self.author.pk, 'genre': 'poema', 'body': 'verso'}
        datos.update(extra)
        return self.client.post('/api/admin/library/', datos, format='multipart')

    def test_crea_una_pieza(self):
        response = self._crear()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'masa')

    def test_el_listado_incluye_borradores(self):
        self._crear()
        response = self.client.get('/api/admin/library/')
        self.assertEqual(len(response.data), 1)

    def test_asigna_narrador(self):
        narrador = Author.objects.create(name='Bruno Odar')
        response = self._crear(narrator=narrador.pk)
        self.assertEqual(response.data['narrator']['name'], 'Bruno Odar')

    def test_publica_con_patch(self):
        pk = self._crear().data['id']
        response = self.client.patch(f'/api/admin/library/{pk}/', {'status': 'published'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(LibraryPiece.objects.get(pk=pk).status, 'published')

    def test_no_borra_si_no_esta_en_papelera(self):
        # Mismo criterio que Article: el borrado definitivo siempre pasa
        # primero por la papelera, para que no sea un clic de distancia.
        pk = self._crear().data['id']
        response = self.client.delete(f'/api/admin/library/{pk}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(LibraryPiece.objects.filter(pk=pk).exists())

    def test_borra_si_esta_en_papelera(self):
        pk = self._crear(status='trashed').data['id']
        response = self.client.delete(f'/api/admin/library/{pk}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LibraryPiece.objects.filter(pk=pk).exists())

    def test_sin_sesion_no_se_puede(self):
        self.client.credentials()
        self.assertIn(self.client.get('/api/admin/library/').status_code, (401, 403))

    def test_borrar_un_autor_con_piezas_da_400_con_mensaje(self):
        # AdminAuthorDeleteView ya atrapa ProtectedError y lo traduce a 400.
        # Al sumar una FK PROTECT nueva desde LibraryPiece, ese camino tiene que
        # seguir funcionando: si no, borrar un autor tira un 500.
        self._crear()
        response = self.client.delete(f'/api/admin/authors/{self.author.pk}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)
```

Ese último caso obliga a revisar el mensaje de `AdminAuthorDeleteView`
(`admin_views.py:132-135`), que hoy dice "este autor tiene publicaciones o
volúmenes asociados". Actualizarlo para que también nombre las piezas de la
Biblioteca; si no, el mensaje miente sobre por qué falló.

- [ ] **Paso 2: Correr y verificar que fallan**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend
.venv/bin/python manage.py test content.tests.LibraryAdminTests 2>&1 | tail -15
```

Esperado: 404 — las rutas no existen.

- [ ] **Paso 3: Escribir el serializer de admin**

Agregar en `backend/content/serializers.py`, justo después de `LibrarySerializer`:

```python
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
        # `audioUrl` (heredados) son los de lectura. Los cuatro tienen que estar:
        # un campo declarado arriba pero ausente de esta lista lo ignora DRF en
        # silencio, y la subida del audio no llegaría nunca al modelo.
        fields = LibrarySerializer.Meta.fields + ['status', 'coverImage', 'audio']

    def to_representation(self, instance):
        # PrimaryKeyRelatedField devolvería el id pelado; el panel necesita el
        # nombre para mostrarlo en la tabla sin un segundo pedido.
        data = super().to_representation(instance)
        data['author'] = AuthorSerializer(instance.author, context=self.context).data
        data['narrator'] = (
            AuthorSerializer(instance.narrator, context=self.context).data if instance.narrator else None
        )
        return data
```

- [ ] **Paso 4: Escribir las vistas de admin**

Agregar al final de `backend/content/admin_views.py`:

```python
class AdminLibraryListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/admin/library/ — el catálogo completo (con borradores y
    papelera, a diferencia del endpoint público) y la carga de piezas nuevas.
    Acepta multipart/form-data: entran la portada y el audio en el mismo envío."""

    serializer_class = LibraryAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None
    queryset = LibraryPiece.objects.select_related('author', 'narrator').all()


class AdminLibraryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/admin/library/<id>/.

    No hay endpoints de papelera/restaurar aparte: `status` es escribible, así
    que mandar a la papelera es un PATCH más. DELETE sigue el mismo criterio
    que Article — solo se permite si la pieza ya está en `trashed`, para que
    el borrado definitivo nunca esté a un clic del listado activo.
    """

    serializer_class = LibraryAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]
    queryset = LibraryPiece.objects.select_related('author', 'narrator').all()

    def perform_destroy(self, instance):
        if instance.status != 'trashed':
            raise ValidationError('Solo se puede eliminar definitivamente una pieza que ya está en la papelera.')
        instance.delete()
```

Agregar `LibraryPiece` al import de modelos (`admin_views.py:12`) y
`LibraryAdminSerializer` al de serializers (`admin_views.py:13-20`).

- [ ] **Paso 5: Registrar las rutas**

En `backend/content/admin_urls.py`, agregar después de las de `events/`:

```python
    path('library/', admin_views.AdminLibraryListCreateView.as_view(), name='admin-library-list'),
    path('library/<int:pk>/', admin_views.AdminLibraryDetailView.as_view(), name='admin-library-detail'),
```

- [ ] **Paso 6: Correr y verificar que pasan**

```bash
.venv/bin/python manage.py test content.tests.LibraryAdminTests 2>&1 | rg "^(OK|Ran |FAILED)"
.venv/bin/python manage.py test content 2>&1 | rg "^(OK|Ran |FAILED)"
```

Esperado: `OK` en las dos.

- [ ] **Paso 7: Commit** (lo corre la persona)

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend
git add content/serializers.py content/admin_views.py content/admin_urls.py content/tests.py
git commit -m "feat(biblioteca): API de administración"
```

---

### Task 4: `renderLiteraryMarkdown` — que los versos no se pierdan

**Archivos:**
- Modificar: `frontend/src/lib/markdown.ts`
- Crear: `frontend/src/lib/markdown-literario.test.ts`

**Interfaces:**
- Consume: `alignBlockExtension` y la configuración de saneado que ya viven en
  `markdown.ts`
- Produce: `export function renderLiteraryMarkdown(body?: string): string`

**Por qué:** markdown colapsa el salto de línea simple. Verificado con el
renderizador actual del proyecto: cuatro versos entran y sale un párrafo corrido.
Para una biblioteca de poesía eso arruina la obra en silencio.

- [ ] **Paso 1: Escribir las pruebas que fallan**

Crear `frontend/src/lib/markdown-literario.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { renderLiteraryMarkdown, renderMarkdown } from './markdown';

describe('renderLiteraryMarkdown', () => {
  const poema = 'Me moriré en París con aguacero,\nun día del cual tengo ya el recuerdo.';

  it('conserva el salto de verso', () => {
    expect(renderLiteraryMarkdown(poema)).toContain('<br />');
  });

  it('separa las estrofas en párrafos', () => {
    const html = renderLiteraryMarkdown('Primer verso\nsegundo verso\n\nOtra estrofa');
    expect(html.match(/<p>/g)).toHaveLength(2);
  });

  it('sigue permitiendo cursiva y negrita', () => {
    expect(renderLiteraryMarkdown('*Trilce* y **Masa**')).toContain('<em>Trilce</em>');
    expect(renderLiteraryMarkdown('*Trilce* y **Masa**')).toContain('<strong>Masa</strong>');
  });

  it('sanea igual que el renderizador de artículos', () => {
    expect(renderLiteraryMarkdown('<script>alert(1)</script>')).not.toContain('<script>');
  });

  it('con texto vacío devuelve cadena vacía', () => {
    expect(renderLiteraryMarkdown()).toBe('');
    expect(renderLiteraryMarkdown('')).toBe('');
  });
});

describe('renderMarkdown (artículos) no cambia', () => {
  it('sigue colapsando el salto simple', () => {
    // Si esto falla, el cambio se filtró a los artículos, donde el
    // comportamiento actual es el correcto.
    expect(renderMarkdown('una línea\notra línea')).not.toContain('<br />');
  });
});
```

- [ ] **Paso 2: Correr y verificar que fallan**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec vitest run src/lib/markdown-literario.test.ts 2>&1 | tail -15
```

Esperado: `renderLiteraryMarkdown is not a function`.

- [ ] **Paso 3: Extraer el saneado a una función compartida**

En `frontend/src/lib/markdown.ts`, cambiar el `import` de la primera línea:

```ts
import { marked, Marked } from 'marked';
```

Después, sacar todo el objeto de configuración que hoy está dentro de
`renderMarkdown` (desde `allowedTags:` hasta el cierre del objeto) a una función
propia, y dejar que las dos entradas la usen:

```ts
/**
 * El saneado es el mismo para los artículos y para la Biblioteca: cambia qué
 * markdown se acepta, no qué HTML es seguro publicar. Vivía embebido en
 * renderMarkdown; se extrae acá para que las dos entradas compartan
 * exactamente la misma lista blanca y no se puedan desincronizar.
 */
function sanear(html: string): string {
  return sanitizeHtml(html, {
    // …la configuración que ya existía, movida tal cual, sin cambios…
  });
}

export function renderMarkdown(body?: string): string {
  if (!body) return '';
  return sanear(marked.parse(body, { async: false }) as string);
}

/**
 * Igual que renderMarkdown, pero para la Biblioteca: respeta cada salto de
 * línea.
 *
 * Markdown normal colapsa el salto simple, así que un poema pegado tal cual
 * sale como prosa corrida y se pierden los versos. `breaks: true` lo arregla
 * y deja intactas las cursivas y negritas, que en literatura hacen falta.
 *
 * Va en su propia instancia de `marked` y no en la global: `breaks` es
 * configuración de instancia, no un parámetro por llamada, así que activarlo
 * sobre la global cambiaría también los artículos, donde el comportamiento
 * actual es el que se quiere. La prueba de arriba cuida justo eso.
 */
const markedLiterario = new Marked({ breaks: true });
markedLiterario.use({ extensions: [alignBlockExtension as never] });

export function renderLiteraryMarkdown(body?: string): string {
  if (!body) return '';
  return sanear(markedLiterario.parse(body, { async: false }) as string);
}
```

- [ ] **Paso 4: Correr y verificar que pasan**

```bash
pnpm exec vitest run src/lib/markdown-literario.test.ts 2>&1 | rg "Tests |Test Files"
```

Esperado: `Tests 6 passed (6)`.

- [ ] **Paso 5: Correr toda la suite del frontend**

```bash
pnpm exec vitest run 2>&1 | rg "Tests |Test Files"
pnpm exec astro check 2>&1 | tail -4
```

Esperado: todo pasa, `0 errors`. Las pruebas de markdown que ya existían no deben
haberse movido — si alguna falla, el saneado se copió mal al extraerlo.

- [ ] **Paso 6: Commit** (lo corre la persona)

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
git add src/lib/markdown.ts src/lib/markdown-literario.test.ts
git commit -m "feat(biblioteca): renderizador que respeta los saltos de verso"
```

---

### Task 5: Tipos, cliente público y lista blanca del proxy

**Archivos:**
- Modificar: `frontend/src/lib/types.ts`
- Modificar: `frontend/src/lib/api.ts`
- Modificar: `frontend/src/lib/admin-path.ts`
- Modificar: `frontend/src/pages/api/admin-proxy/[...path].ts:10`
- Crear: `frontend/src/lib/admin-path.test.ts` (o agregar al que exista)

**Interfaces:**
- Consume: `apiFetch`, `apiFetchOrNull` (`api.ts:19-32`), `Author` (`types.ts:3`)
- Produce: `interface LibraryPiece`, `type LibraryGenre`;
  `getLibraryPieces(genre?)`, `getLibraryPiece(slug)`;
  `export const ADMIN_RESOURCE_RE`

**Por qué el proxy:** hoy la lista blanca de recursos está embebida en la ruta. Sin
agregar `library` ahí, el panel da 404 aunque el backend esté perfecto — es
exactamente lo que deja a `Volume` sin panel. Se extrae a `admin-path.ts` para poder
probarla.

- [ ] **Paso 1: Escribir la prueba que falla**

Crear `frontend/src/lib/admin-path.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { ADMIN_RESOURCE_RE } from './admin-path';

describe('lista blanca de recursos del panel', () => {
  it.each(['articles/', 'authors/3/', 'events/', 'media/', 'library/', 'library/12/'])(
    'acepta %s',
    (ruta) => expect(ADMIN_RESOURCE_RE.test(ruta)).toBe(true),
  );

  it.each(['volumes/', 'users/', 'librarything/', '../secreto'])(
    'rechaza %s',
    (ruta) => expect(ADMIN_RESOURCE_RE.test(ruta)).toBe(false),
  );
});
```

`librarything/` está en la lista de rechazo a propósito: sin el `(\/|$)` final, el
prefijo `library` dejaría pasar cualquier ruta que empiece igual.

- [ ] **Paso 2: Correr y verificar que falla**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec vitest run src/lib/admin-path.test.ts 2>&1 | tail -10
```

Esperado: `ADMIN_RESOURCE_RE is not exported`.

- [ ] **Paso 3: Extraer y ampliar la expresión**

Agregar a `frontend/src/lib/admin-path.ts`:

```ts
/**
 * Recursos del backend que el proxy tiene permitido reenviar. Es una lista
 * blanca: lo que no esté acá devuelve 404 antes de salir del frontend.
 *
 * Vivía embebida en la ruta del proxy. Se saca acá para poder probarla, porque
 * olvidarse de agregar un recurso es el error clásico al sumar una sección —
 * el backend responde perfecto y el panel igual da 404.
 */
export const ADMIN_RESOURCE_RE = /^(articles|authors|tags|regions|categories|events|media|library)(\/|$)/;
```

En `frontend/src/pages/api/admin-proxy/[...path].ts`, cambiar la línea 2 y la 10:

```ts
import { ADMIN_RESOURCE_RE, canonicalAdminPath } from '../../../lib/admin-path';
```

```ts
  const allowedResource = ADMIN_RESOURCE_RE.test(path);
```

- [ ] **Paso 4: Agregar los tipos**

Agregar a `frontend/src/lib/types.ts`:

```ts
export type LibraryGenre = 'cuento' | 'poema' | 'cronica';

/** Una obra literaria de la Biblioteca. No es un Article: ver el diseño en
 *  backend/docs/specs/2026-09-21-biblioteca-design.md. */
export interface LibraryPiece {
  id: string;
  slug: string;
  title: string;
  genre: LibraryGenre;
  body: string;
  author: Author;
  /** Quien pone la voz. Null mientras la pieza no esté narrada. */
  narrator: Author | null;
  coverImageUrl: string;
  audioUrl: string;
  sourceNote: string;
  publishedAt: string | null;
}
```

- [ ] **Paso 5: Agregar el cliente público**

Agregar a `frontend/src/lib/api.ts`, después del bloque de eventos:

```ts
// ────────────────────────────────────────────────────────────────────────
// Biblioteca

export async function getLibraryPieces(genre?: LibraryGenre): Promise<LibraryPiece[]> {
  return apiFetch(`/library/${genre ? `?genre=${genre}` : ''}`);
}

export async function getLibraryPiece(slug: string): Promise<LibraryPiece | null> {
  return apiFetchOrNull(`/library/${encodeURIComponent(slug)}/`);
}
```

Agregar `LibraryGenre` y `LibraryPiece` al import de tipos de `api.ts:14`.

- [ ] **Paso 6: Correr y verificar**

```bash
pnpm exec vitest run src/lib/admin-path.test.ts 2>&1 | rg "Tests "
pnpm exec astro check 2>&1 | tail -4
```

Esperado: `Tests 10 passed`, `0 errors`.

- [ ] **Paso 7: Commit** (lo corre la persona)

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
git add src/lib/types.ts src/lib/api.ts src/lib/admin-path.ts src/lib/admin-path.test.ts "src/pages/api/admin-proxy/[...path].ts"
git commit -m "feat(biblioteca): tipos, cliente público y proxy"
```

---

### Task 6: Agrupación alfabética

**Archivos:**
- Crear: `frontend/src/lib/library-index.ts`
- Crear: `frontend/src/lib/library-index.test.ts`

**Interfaces:**
- Consume: `LibraryPiece` (Task 5)
- Produce: `export function agruparPorLetra(piezas: LibraryPiece[]): LetraConPiezas[]`
  y `export interface LetraConPiezas { letra: string; piezas: LibraryPiece[] }`

**Por qué aparte:** es la única lógica real del índice, y tiene casos molestos
—tildes, mayúsculas, títulos que empiezan con número o comilla— que conviene probar
sin levantar una página.

- [ ] **Paso 1: Escribir las pruebas que fallan**

Crear `frontend/src/lib/library-index.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { agruparPorLetra } from './library-index';
import type { LibraryPiece } from './types';

const pieza = (title: string): LibraryPiece => ({
  id: '1', slug: title.toLowerCase(), title, genre: 'poema', body: '',
  author: { id: '1', name: 'Autor' }, narrator: null,
  coverImageUrl: '', audioUrl: '', sourceNote: '', publishedAt: null,
});

describe('agruparPorLetra', () => {
  it('agrupa por la inicial', () => {
    const grupos = agruparPorLetra([pieza('Masa'), pieza('Melgar'), pieza('Trilce')]);
    expect(grupos.map((g) => g.letra)).toEqual(['M', 'T']);
    expect(grupos[0].piezas).toHaveLength(2);
  });

  it('la tilde cae en la letra sin tilde', () => {
    // "Álbum" tiene que ir con la A, no en un grupo "Á" aparte al final.
    expect(agruparPorLetra([pieza('Álbum')])[0].letra).toBe('A');
  });

  it('no distingue mayúsculas', () => {
    expect(agruparPorLetra([pieza('masa'), pieza('Melgar')])[0].letra).toBe('M');
  });

  it('las letras salen ordenadas', () => {
    expect(agruparPorLetra([pieza('Trilce'), pieza('Álbum'), pieza('Masa')]).map((g) => g.letra))
      .toEqual(['A', 'M', 'T']);
  });

  it('dentro de cada letra ordena por título', () => {
    expect(agruparPorLetra([pieza('Melgar'), pieza('Masa')])[0].piezas.map((p) => p.title))
      .toEqual(['Masa', 'Melgar']);
  });

  it('lo que no empieza con letra va a #', () => {
    const grupos = agruparPorLetra([pieza('1922'), pieza('«Comillas»'), pieza('Masa')]);
    expect(grupos.map((g) => g.letra)).toEqual(['M', '#']);
    expect(grupos[1].piezas).toHaveLength(2);
  });

  it('sin piezas devuelve lista vacía', () => {
    expect(agruparPorLetra([])).toEqual([]);
  });
});
```

- [ ] **Paso 2: Correr y verificar que fallan**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec vitest run src/lib/library-index.test.ts 2>&1 | tail -10
```

Esperado: no encuentra `./library-index`.

- [ ] **Paso 3: Escribir la implementación**

Crear `frontend/src/lib/library-index.ts`:

```ts
import type { LibraryPiece } from './types';

export interface LetraConPiezas {
  letra: string;
  piezas: LibraryPiece[];
}

/** Grupo donde caen los títulos que no empiezan con una letra: números,
 *  comillas, signos. Va último, después de la Z. */
const OTROS = '#';

function inicial(title: string): string {
  // `normalize('NFD')` separa la letra de su tilde y el reemplazo borra la
  // tilde suelta, así "Álbum" cae en la A y no en un grupo "Á" al final.
  const limpio = title.trim().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const primera = limpio.charAt(0).toUpperCase();
  return /^[A-Z]$/.test(primera) ? primera : OTROS;
}

export function agruparPorLetra(piezas: LibraryPiece[]): LetraConPiezas[] {
  const grupos = new Map<string, LibraryPiece[]>();
  for (const pieza of piezas) {
    const letra = inicial(pieza.title);
    grupos.set(letra, [...(grupos.get(letra) ?? []), pieza]);
  }

  return [...grupos.entries()]
    .map(([letra, lista]) => ({
      letra,
      // `localeCompare` con 'es' para que la ñ y las tildes ordenen como
      // corresponde en castellano, no por código de carácter.
      piezas: [...lista].sort((a, b) => a.title.localeCompare(b.title, 'es')),
    }))
    .sort((a, b) => {
      if (a.letra === OTROS) return 1;
      if (b.letra === OTROS) return -1;
      return a.letra.localeCompare(b.letra, 'es');
    });
}
```

- [ ] **Paso 4: Correr y verificar que pasan**

```bash
pnpm exec vitest run src/lib/library-index.test.ts 2>&1 | rg "Tests "
```

Esperado: `Tests 7 passed (7)`.

- [ ] **Paso 5: Commit** (lo corre la persona)

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
git add src/lib/library-index.ts src/lib/library-index.test.ts
git commit -m "feat(biblioteca): agrupación alfabética del índice"
```

---

### Task 7: Cliente de administración

**Archivos:**
- Crear: `frontend/src/lib/library.ts`
- Modificar: `frontend/src/lib/api.ts` (agregar `getLibraryForAdmin`)

**Interfaces:**
- Consume: `authFetch` (`lib/auth.ts`), `adminFetch` (`api.ts`), `LibraryPiece` (Task 5)
- Produce: `interface AdminLibraryPiece extends LibraryPiece { status }`,
  `interface LibraryDraft`, y las funciones `getLibraryPiecesForAdmin`,
  `createLibraryPiece`, `updateLibraryPiece`, `trashLibraryPiece`,
  `restoreLibraryPiece`, `deleteLibraryPiecePermanently`

- [ ] **Paso 1: Escribir el cliente**

Crear `frontend/src/lib/library.ts`, calcado de `lib/events.ts`:

```ts
/**
 * Gestión de la Biblioteca contra el backend real — mismo patrón que
 * lib/events.ts. Solo se importa desde <script> de cliente: usa authFetch()
 * de lib/auth.ts (Bearer + renovación automática de sesión).
 *
 * La lectura pública NO pasa por acá: eso es getLibraryPieces() en lib/api.ts,
 * que corre server-side y solo devuelve las publicadas.
 */
import { authFetch } from './auth';
import type { LibraryGenre, LibraryPiece } from './types';

/** La pieza como la ve el panel: incluye `status`, que el público omite. */
export interface AdminLibraryPiece extends LibraryPiece {
  status: 'published' | 'draft' | 'trashed';
}

export interface LibraryDraft {
  title: string;
  author: string;
  narrator?: string | null;
  genre: LibraryGenre;
  body: string;
  sourceNote: string;
  status: AdminLibraryPiece['status'];
  coverImage?: File | null;
  audio?: File | null;
}

/** Viaja como multipart porque entran portada y audio; el backend parsea el
 *  resto de los campos igual que si fuera JSON. */
function toFormData(draft: Partial<LibraryDraft>): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(draft)) {
    if (value === undefined || value === null) continue;
    form.append(key, value as string | Blob);
  }
  return form;
}

async function readError(res: Response, fallback: string): Promise<never> {
  const body = await res.json().catch(() => null);
  if (body && typeof body === 'object') {
    // DRF devuelve {campo: ["mensaje"]} — mostrar el primer mensaje concreto
    // es más útil que un "status 400" pelado.
    const first = Object.values(body).flat()[0];
    if (typeof first === 'string') throw new Error(first);
  }
  throw new Error(`${fallback} (status ${res.status}).`);
}

export async function getLibraryPiecesForAdmin(): Promise<AdminLibraryPiece[]> {
  const res = await authFetch('/admin/library/');
  if (!res.ok) throw new Error(`No se pudo cargar la Biblioteca (status ${res.status}).`);
  return res.json();
}

export async function createLibraryPiece(draft: LibraryDraft): Promise<AdminLibraryPiece> {
  const res = await authFetch('/admin/library/', { method: 'POST', body: toFormData(draft) });
  if (!res.ok) await readError(res, 'No se pudo crear la pieza');
  return res.json();
}

export async function updateLibraryPiece(id: string, draft: Partial<LibraryDraft>): Promise<AdminLibraryPiece> {
  const res = await authFetch(`/admin/library/${id}/`, { method: 'PATCH', body: toFormData(draft) });
  if (!res.ok) await readError(res, 'No se pudo guardar la pieza');
  return res.json();
}

/** La papelera es un PATCH de `status`, no un endpoint aparte. */
export async function trashLibraryPiece(id: string): Promise<void> {
  await updateLibraryPiece(id, { status: 'trashed' });
}

/** Restaura siempre a borrador: no se guarda el estado previo a la papelera,
 *  mismo criterio que las publicaciones. */
export async function restoreLibraryPiece(id: string): Promise<void> {
  await updateLibraryPiece(id, { status: 'draft' });
}

export async function deleteLibraryPiecePermanently(id: string): Promise<void> {
  const res = await authFetch(`/admin/library/${id}/`, { method: 'DELETE' });
  if (!res.ok) await readError(res, 'No se pudo eliminar la pieza');
}
```

- [ ] **Paso 2: Agregar la lectura server-side para el listado del panel**

Agregar a `frontend/src/lib/api.ts`, junto a `getEventsForAdmin`:

```ts
export async function getLibraryForAdmin(): Promise<AdminLibraryPiece[]> {
  const res = await adminFetch('/admin/library/');
  if (!res.ok) throw new Error(`No se pudo obtener la Biblioteca (status ${res.status}).`);
  return res.json();
}
```

Agregar `import type { AdminLibraryPiece } from './library';` arriba, junto al
`import type { AdminEvent } from './events';` que ya existe.

- [ ] **Paso 3: Verificar tipos**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec astro check 2>&1 | tail -4
```

Esperado: `0 errors`.

- [ ] **Paso 4: Commit** (lo corre la persona)

```bash
git add src/lib/library.ts src/lib/api.ts
git commit -m "feat(biblioteca): cliente de administración"
```

---

### Task 8: Panel — listado `/admin/biblioteca`

**Archivos:**
- Crear: `frontend/src/pages/admin/biblioteca/index.astro`
- Crear: `frontend/src/components/admin/LibraryTable.astro`
- Modificar: `frontend/src/components/admin/AdminSidebar.astro:9-15`

**Interfaces:**
- Consume: `getLibraryForAdmin` (Task 7), `trashLibraryPiece`,
  `restoreLibraryPiece`, `deleteLibraryPiecePermanently` (Task 7),
  `AdminLayout`, `SearchInput`, `Button`, `confirmAdminAction`, `showAdminNotice`
- Produce: la ruta `/admin/biblioteca/`

**Patrón:** copiar `frontend/src/pages/admin/index.astro` (pestañas Activas/Papelera,
buscador, conteo) y `PublicationsTable.astro`, cambiando artículo por pieza y
agregando la columna de narrador.

**Cuidado con esto:** en `admin/index.astro:163-188` hay un comentario largo sobre
`event.currentTarget`. Se guarda el botón **antes** del `await` del diálogo, porque
después del primer `await` el navegador lo deja en `null` y el borrado no ocurre nunca,
en silencio. Mantener ese patrón al copiar.

- [ ] **Paso 1: Agregar la entrada del menú**

En `frontend/src/components/admin/AdminSidebar.astro`, en el array `ITEMS`, después de
Publicaciones:

```ts
  { label: 'Biblioteca', href: '/admin/biblioteca/' },
```

- [ ] **Paso 2: Crear la tabla**

Crear `frontend/src/components/admin/LibraryTable.astro` copiando
`PublicationsTable.astro`. Columnas: Título · Autor · Narrador · Género · Estado ·
Acciones. Cada fila lleva `data-piece-id`, `data-status` y los botones
`data-action="trash|restore|delete"`, igual que la tabla de publicaciones. El título
enlaza a `/admin/biblioteca/{pieza.id}/`. Cuando `narrator` es `null`, la celda
muestra `—`, no vacío.

- [ ] **Paso 3: Crear la página**

Crear `frontend/src/pages/admin/biblioteca/index.astro` copiando
`pages/admin/index.astro`. Cambios: `export const prerender = false;` (igual),
`getLibraryForAdmin()` en vez de `getAllArticlesForAdmin()`, `LibraryTable` en vez de
`PublicationsTable`, el botón "Nueva pieza" apunta a `/admin/biblioteca/new/`, y el
`<script>` importa de `lib/library.ts`.

- [ ] **Paso 4: Verificar en el navegador**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec astro check 2>&1 | tail -4
pnpm exec astro dev --port 4321
```

Abrir `http://localhost:4321/admin/biblioteca/`. Verificar a mano:
- La entrada "Biblioteca" aparece en el menú y queda marcada como activa.
- Sin piezas, la tabla muestra el mensaje de vacío y no revienta.
- Las pestañas Activas / Papelera cambian el conteo.

- [ ] **Paso 5: Commit** (lo corre la persona)

```bash
git add src/pages/admin/biblioteca/index.astro src/components/admin/LibraryTable.astro src/components/admin/AdminSidebar.astro
git commit -m "feat(biblioteca): listado del panel"
```

---

### Task 9: Panel — editor `/admin/biblioteca/[id]`

**Archivos:**
- Crear: `frontend/src/pages/admin/biblioteca/[id].astro`

**Interfaces:**
- Consume: `RichTextEditor`, `FileField`, `AdminLayout`, `Button`,
  `getAuthorsForAdmin` (`lib/api.ts`), `createLibraryPiece`, `updateLibraryPiece`
  (Task 7), `getLibraryForAdmin` (Task 7)
- Produce: las rutas `/admin/biblioteca/{id}/` y `/admin/biblioteca/new/`

**Patrón:** copiar `frontend/src/pages/admin/publicaciones/[id].astro` y **recortar**:
sin etiquetas, sin regiones, sin programación, sin YouTube ni Spotify, sin resumen.

Campos del formulario:

| Campo | Control | Notas |
|---|---|---|
| Título | texto | requerido |
| Autor | `<select>` | de `getAuthorsForAdmin()`, requerido |
| Narrador | `<select>` | mismo listado, con opción vacía "Sin narrador" |
| Género | `<select>` | Cuento / Poema / Crónica |
| Texto | `RichTextEditor` | |
| Nota de origen | texto | placeholder: `de Trilce, 1922` |
| Portada | `FileField` | `recommendedSize="1400 × 1400 px"`, `ratio="1:1"`, `cropNote="No se recorta."` |
| Audio | `FileField` | `accept="audio/*"`, `cropNote="MP3, 96 kbps."` |

Botones: Guardar borrador · Publicar, como en el editor de publicaciones.

- [ ] **Paso 1: Crear la página**

Copiar `pages/admin/publicaciones/[id].astro` a `pages/admin/biblioteca/[id].astro` y
aplicar los recortes y campos de la tabla de arriba. El `id` especial `new` significa
pieza nueva (mismo criterio que publicaciones): si `Astro.params.id === 'new'` no se
busca nada y el formulario arranca vacío.

- [ ] **Paso 2: Verificar el flujo completo a mano**

Con el backend y el frontend corriendo:

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/backend && .venv/bin/python manage.py runserver 8001
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend && pnpm exec astro dev --port 4321
```

En `http://localhost:4321/admin/biblioteca/new/`:
- Cargar una pieza con portada y audio, guardar como borrador. Aparece en el listado.
- Reabrirla: los campos vuelven con lo cargado, incluidas portada y audio.
- Cambiar el narrador y guardar. El cambio persiste.
- Publicarla. Cambia de estado en el listado.
- Enviarla a la papelera y restaurarla.

- [ ] **Paso 3: Verificar tipos y compilación**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec astro check 2>&1 | tail -4
pnpm build 2>&1 | tail -3
```

Esperado: `0 errors`, `Complete!`.

- [ ] **Paso 4: Commit** (lo corre la persona)

```bash
git add "src/pages/admin/biblioteca/[id].astro"
git commit -m "feat(biblioteca): editor de piezas en el panel"
```

---

### Task 10: Público — índice `/biblioteca`

**Archivos:**
- Crear: `frontend/src/pages/biblioteca/index.astro`
- Crear: `frontend/src/components/content/LibraryIndex.astro`
- Crear: `frontend/src/components/content/LibraryRow.astro`

**Interfaces:**
- Consume: `getLibraryPieces` (Task 5), `agruparPorLetra` (Task 6), `BaseLayout`
- Produce: la ruta `/biblioteca`

**Forma:** como la referencia del BBVA — una barra de letras arriba que ancla a cada
grupo, y debajo las columnas por letra. Cada fila: título (enlace a la pieza), autor
debajo, y si hay narrador un ▶ con su nombre.

- [ ] **Paso 1: Crear `LibraryRow.astro`**

```astro
---
import type { LibraryPiece } from '../../lib/types';

export interface Props {
  piece: LibraryPiece;
}

const { piece } = Astro.props;
// El ▶ solo tiene sentido si hay algo que reproducir. Una pieza puede estar
// cargada y todavía sin narrar.
const narrada = Boolean(piece.audioUrl && piece.narrator);
---

<article class="library-row">
  {/* Toda la fila es UN solo enlace. El ▶ es indicador, no botón: la
      reproducción pasa en la página de la pieza. Si fuera un botón aparte
      habría dos objetivos de clic superpuestos, que en un dedo de celular es
      una lotería. */}
  <a class="library-row__link" href={`/biblioteca/${piece.slug}/`}>
    <h3 class="library-row__title">{piece.title}</h3>
    <p class="library-row__author">{piece.author.name}</p>
    {narrada && (
      <p class="library-row__narrator">
        <svg class="library-row__play" width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" stroke-width="1.5" />
          <path d="M8 6.5l5 3.5-5 3.5z" fill="currentColor" />
        </svg>
        <span>{piece.narrator!.name}</span>
      </p>
    )}
  </a>
</article>

<style>
  .library-row__link {
    display: flex;
    flex-direction: column;
    gap: var(--space-2xs);
    padding-block: var(--space-sm);
    color: inherit;
    text-decoration: none;
  }

  .library-row__title {
    font-size: var(--font-size-lg);
    color: var(--color-primary);
  }

  .library-row__link:hover .library-row__title {
    text-decoration: underline;
  }

  .library-row__author {
    font-size: var(--font-size-sm);
    color: var(--color-ink-muted);
  }

  .library-row__narrator {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-family: var(--font-label);
    font-size: var(--font-size-sm);
    color: var(--color-ink-muted);
  }

  .library-row__play {
    flex-shrink: 0;
  }
</style>
```

- [ ] **Paso 2: Crear `LibraryIndex.astro`**

```astro
---
import LibraryRow from './LibraryRow.astro';
import type { LetraConPiezas } from '../../lib/library-index';

export interface Props {
  groups: LetraConPiezas[];
}

const { groups } = Astro.props;
---

{groups.length === 0 ? (
  <p class="library-index__empty">Todavía no hay piezas publicadas en la Biblioteca.</p>
) : (
  <>
    <nav class="library-index__letters" aria-label="Ir a una letra">
      {groups.map((g) => (
        <a class="library-index__letter-link" href={`#letra-${g.letra}`}>{g.letra}</a>
      ))}
    </nav>

    <div class="library-index__groups">
      {groups.map((g) => (
        <section class="library-index__group" id={`letra-${g.letra}`}>
          <h2 class="library-index__letter">{g.letra}</h2>
          <div class="library-index__pieces">
            {g.piezas.map((piece) => <LibraryRow piece={piece} />)}
          </div>
        </section>
      ))}
    </div>
  </>
)}

<style>
  .library-index__empty {
    padding-block: var(--space-xl);
    color: var(--color-ink-muted);
    text-align: center;
  }

  .library-index__letters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm) var(--space-md);
    padding-block: var(--space-md);
    border-block: 1px solid var(--color-line);
  }

  .library-index__letter-link {
    font-family: var(--font-label);
    font-weight: var(--font-weight-medium);
    color: var(--color-primary);
  }

  .library-index__groups {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-xl) var(--space-gutter);
    padding-block: var(--space-xl);
  }

  .library-index__group {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-md);
    /* Sin esto el ancla deja el título justo debajo de la cabecera fija y
       parece que el salto no funcionó. */
    scroll-margin-top: var(--space-xl);
  }

  .library-index__letter {
    font-size: var(--font-size-3xl);
    line-height: 1;
    color: var(--color-secondary);
  }

  @media (max-width: 900px) {
    .library-index__groups {
      grid-template-columns: 1fr;
    }
  }
</style>
```

Todos los tokens usados arriba están verificados contra
`frontend/src/styles/tokens.css`. Ojo con uno: **`--space-2xl` no existe** — la escala
de espaciado termina en `--space-xl: 64px` (línea 79). Un `var()` de un token
inexistente no rompe nada a la vista: la propiedad se descarta en silencio y el ancla
queda tapada por la cabecera sin que nadie note por qué.

- [ ] **Paso 3: Crear la página**

Crear `frontend/src/pages/biblioteca/index.astro`:

```astro
---
export const prerender = false;

import BaseLayout from '../../layouts/BaseLayout.astro';
import LibraryIndex from '../../components/content/LibraryIndex.astro';
import { getLibraryPieces } from '../../lib/api';
import { agruparPorLetra } from '../../lib/library-index';
import type { LibraryGenre } from '../../lib/types';

const GENEROS: { valor: LibraryGenre | ''; etiqueta: string }[] = [
  { valor: '', etiqueta: 'Todo' },
  { valor: 'cuento', etiqueta: 'Cuentos' },
  { valor: 'poema', etiqueta: 'Poemas' },
  { valor: 'cronica', etiqueta: 'Crónicas' },
];

const generoPedido = new URL(Astro.request.url).searchParams.get('genre') ?? '';
const genero = GENEROS.some((g) => g.valor === generoPedido) ? (generoPedido as LibraryGenre | '') : '';
const piezas = await getLibraryPieces(genero || undefined);
const grupos = agruparPorLetra(piezas);
---

<BaseLayout title="Biblioteca" description="Cuentos, poemas y crónicas de autores, para leer y escuchar.">
  <!-- título de sección, filtro de género y <LibraryIndex groups={grupos} /> -->
</BaseLayout>
```

`prerender = false` por el mismo motivo que las páginas de panel: con `static` la
página quedaría congelada con las piezas del momento del build.

El filtro valida contra `GENEROS` antes de pasar el valor al cliente: sin eso,
cualquiera podría meter texto arbitrario en el parámetro y llegaría tal cual a la URL
de la API.

- [ ] **Paso 4: Verificar a mano**

Con datos de prueba cargados desde el panel, abrir `http://localhost:4321/biblioteca`:
- Las letras de la barra saltan al grupo correcto.
- El filtro de género recarga y filtra.
- Sin piezas publicadas, la página muestra un mensaje y no una grilla vacía.
- A 390px de ancho, una sola columna y sin desborde horizontal.

- [ ] **Paso 5: Commit** (lo corre la persona)

```bash
git add src/pages/biblioteca/index.astro src/components/content/LibraryIndex.astro src/components/content/LibraryRow.astro
git commit -m "feat(biblioteca): índice alfabético público"
```

---

### Task 11: Público — la pieza `/biblioteca/[slug]`

**Archivos:**
- Crear: `frontend/src/pages/biblioteca/[slug].astro`

**Interfaces:**
- Consume: `getLibraryPiece` (Task 5), `renderLiteraryMarkdown` (Task 4),
  `AudioPlayer` (`components/media/AudioPlayer.astro`), `BaseLayout`

- [ ] **Paso 1: Crear la página**

Crear `frontend/src/pages/biblioteca/[slug].astro`:

```astro
---
export const prerender = false;

import BaseLayout from '../../layouts/BaseLayout.astro';
import AudioPlayer from '../../components/media/AudioPlayer.astro';
import { getLibraryPiece } from '../../lib/api';
import { renderLiteraryMarkdown } from '../../lib/markdown';

const { slug } = Astro.params;
const piece = await getLibraryPiece(slug!);
if (!piece) return Astro.redirect('/404');

// renderLiteraryMarkdown y NO renderMarkdown: este es el único lugar donde los
// saltos de verso importan. Con el renderizador de artículos, un poema sale
// como prosa corrida.
const cuerpo = renderLiteraryMarkdown(piece.body);
---

<BaseLayout title={piece.title} description={`${piece.title}, de ${piece.author.name}.`}>
  <!-- portada, título, autor, AudioPlayer si hay audioUrl, cuerpo con set:html, sourceNote -->
</BaseLayout>
```

El `AudioPlayer` solo se renderiza si `piece.audioUrl`. Si hay narrador, el título del
reproductor es `Narrado por {piece.narrator.name}`; si no, `Narración`.

`sourceNote` va al pie de la pieza, en letra chica, como crédito de la fuente.

- [ ] **Paso 2: Verificar que los versos sobreviven de punta a punta**

Cargar desde el panel una pieza cuyo cuerpo sea:

```
Me moriré en París con aguacero,
un día del cual tengo ya el recuerdo.

Me moriré en París —y no me corro—
tal vez un jueves, como es hoy, de otoño.
```

Abrirla en `/biblioteca/<slug>/` y confirmar que se ven **cuatro versos en dos
estrofas**, no un párrafo corrido. Este es el punto que el plan entero cuida.

- [ ] **Paso 3: Verificar el audio**

Con una pieza que tenga audio: reproducir, adelantar arrastrando la barra, y confirmar
que salta (el backend ya sirve `Range`, ver `backend/config/media_views.py`).

- [ ] **Paso 4: Verificar tipos y compilación**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec astro check 2>&1 | tail -4
pnpm exec vitest run 2>&1 | rg "Tests |Test Files"
pnpm build 2>&1 | tail -3
```

Esperado: `0 errors`, todas las pruebas pasan, `Complete!`.

- [ ] **Paso 5: Commit** (lo corre la persona)

```bash
git add "src/pages/biblioteca/[slug].astro"
git commit -m "feat(biblioteca): página de la pieza"
```

---

### Task 12: Navegación pública y buscador

**Archivos:**
- Modificar: `frontend/src/components/layout/Header.astro`
- Modificar: `frontend/src/components/layout/MobileDrawer.astro`
- Modificar: `frontend/src/pages/buscar/index.astro`

**Interfaces:**
- Consume: `getLibraryPieces` (Task 5)

- [ ] **Paso 1: Agregar "Biblioteca" a los dos menús**

Agregar la entrada `{ label: 'Biblioteca', href: '/biblioteca' }` al array de enlaces
de `Header.astro` y al de `MobileDrawer.astro`. Van en los dos: el menú de escritorio y
el cajón de móvil no comparten la lista.

- [ ] **Paso 2: Sumar las piezas al buscador**

En `frontend/src/pages/buscar/index.astro`, agregar un segundo pedido a
`getLibraryPieces()` y mezclar los resultados en el mismo índice. Cada pieza lleva una
etiqueta visible "Biblioteca", para que nadie confunda una obra ajena con una nota de
la revista.

Los filtros por categoría y etiqueta siguen aplicando solo a los artículos: una pieza
no tiene ni una ni otra, así que al activar cualquiera de esos filtros las piezas se
ocultan.

- [ ] **Paso 3: Verificar a mano**

- "Biblioteca" aparece en el menú de escritorio y en el de móvil, y lleva a `/biblioteca`.
- Buscar el título de una pieza la encuentra, marcada como Biblioteca.
- Al filtrar por una categoría, las piezas desaparecen de los resultados.

- [ ] **Paso 4: Verificar compilación**

```bash
cd /Users/just/Documents/PROMESA-IDEMA/el-hacedor/frontend
pnpm exec astro check 2>&1 | tail -4
pnpm build 2>&1 | tail -3
```

- [ ] **Paso 5: Commit** (lo corre la persona)

```bash
git add src/components/layout/Header.astro src/components/layout/MobileDrawer.astro src/pages/buscar/index.astro
git commit -m "feat(biblioteca): navegación y buscador"
```

---

## Cierre de la fase

Con las 12 tareas hechas, El Hacedor puede cargar una pieza con su portada y su audio
desde el panel, y cualquiera puede leerla y escucharla desde el índice alfabético.

Queda para la Fase 2: `/lectores`, las fichas de los narradores. Sale casi gratis
porque `narrator` ya apunta a `Author`.

## Fuera de alcance de este plan

- Reproductor continuo tipo playlist.
- Descarga del audio.
- Transcripción automática.
- Buscador dentro del texto de las piezas.
