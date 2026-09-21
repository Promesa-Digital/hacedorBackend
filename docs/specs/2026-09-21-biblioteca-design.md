# Biblioteca — diseño

Fecha: 2026-09-21
Estado: aprobado, pendiente de plan de implementación

## Qué se pide

El Hacedor quiere una sección nueva para publicar **obra literaria ajena** —cuentos,
poemas y crónicas de autores— con **narración en audio**, y poder cargarla él mismo
desde el panel: el texto, la portada y el audio.

Referencia que dio: <https://encuentratupoema.pe/poemas/> (Fundación BBVA). De ahí
salen dos rasgos que el sitio hoy no tiene:

1. **Índice alfabético por título**, no por fecha de publicación.
2. **El narrador es una persona distinta del autor** — "Ay, amor / Mariano Melgar /
   ▶ Bruno Odar". Hoy la narración de un artículo es solo un archivo, sin a quién
   atribuirla.

## Decisión de fondo: estante aparte

La Biblioteca **no** es una quinta categoría de `Article`.

Un artículo es la crítica que El Hacedor escribe *sobre* la literatura. Una pieza de
biblioteca es la literatura misma, de otro autor. Mezclarlas haría que un poema de
Vallejo salga en el carrusel del inicio y en el RSS como si fuera contenido editorial
firmado por la revista.

Consecuencias:

- Modelo propio, no un `status` ni una `Category` más.
- **No** aparece en el Hero, en "piezas recientes" ni en el RSS.
- **Sí** aparece en el buscador, identificada como Biblioteca.
- El panel de la Biblioteca es más chico que el editor de artículos: no necesita
  etiquetas, regiones, programación ni embebidos de YouTube/Spotify.

## Modelo

`LibraryPiece` en `backend/content/models.py`.

| Campo | Tipo | Notas |
|---|---|---|
| `title` | `CharField(255)` | |
| `slug` | `SlugField(unique)` | automático vía `_unique_slug`, igual que `Article` |
| `author` | `FK Author`, `on_delete=PROTECT` | quien escribió la pieza |
| `narrator` | `FK Author`, `on_delete=SET_NULL`, `null`, `blank` | quien pone la voz |
| `genre` | `CharField(20, choices)` | `cuento` / `poema` / `cronica` |
| `body` | `TextField` | markdown |
| `cover_image` | `ImageField(upload_to='library/')`, `blank`, `null` | |
| `audio` | `FileField(upload_to='library-audio/')`, `blank`, `null` | opcional |
| `source_note` | `CharField(255)`, `blank` | "de *Trilce*, 1922" |
| `status` | `CharField(20, choices)` | `draft` / `published` / `trashed` |
| `published_at` | `DateTimeField`, `null`, `blank` | |

`class Meta: ordering = ['title']` — alfabético, no cronológico. Es el orden que pide
el índice y evita tener que reordenar en cada consulta.

### `narrator` reusa `Author`

No se crea una tabla `Narrator`. `Author` ya tiene nombre, bio, foto y región, que es
exactamente lo que necesita una ficha de lector, y así "Bruno Odar" es la misma fila
esté narrando o escribiendo. Habilita la página `/lectores` de la fase 2 sin trabajo
extra de modelado.

`SET_NULL` y no `PROTECT`: borrar a un narrador no debe bloquearse por las piezas que
narró; la pieza sigue existiendo, se queda sin crédito de voz.

### `save()`

Igual que `Article`: genera el slug si falta, y llama a `optimizar_imagen` sobre
`cover_image` (ver `backend/content/images.py`). No hace falta
`cover_image_orientation`: en la Biblioteca la portada se muestra siempre en la misma
caja.

## Renderizado del texto: los versos

**Este es el punto que más fácil se rompe en silencio.** Markdown colapsa el salto de
línea simple. Verificado con el renderizador real del proyecto:

```
entra: "Me moriré en París con aguacero,\nun día del cual tengo ya el recuerdo."
sale : <p>Me moriré en París con aguacero, un día del cual tengo ya el recuerdo.</p>
```

Un poema pegado tal cual sale como prosa corrida. Para la Biblioteca el renderizador
tiene que respetar cada salto (`breaks: true` en `marked`), que además conserva las
cursivas y negritas que la literatura necesita.

`frontend/src/lib/markdown.ts` hoy exporta `renderMarkdown(body)` apoyado en la
instancia global de `marked`, configurada con la extensión `alignBlock`. Se agrega una
segunda función exportada, `renderLiteraryMarkdown(body)`, construida sobre **su propia
instancia** (`new Marked()`) con `breaks: true` y la misma extensión `alignBlock`.

Tiene que ser una instancia aparte: `breaks` es configuración de instancia, no un
parámetro por llamada, así que activarlo sobre la global cambiaría también los
artículos, donde el comportamiento actual es el que se quiere.

El sanitizador ya permite `br` (`frontend/src/lib/markdown.ts:73`), así que el paso de
saneado no requiere cambios.

## API

### Público

| Ruta | Vista | Devuelve |
|---|---|---|
| `GET /api/library/` | `LibraryListView` | lista, con `?genre=` y `?letter=` opcionales |
| `GET /api/library/<slug>/` | `LibraryDetailView` | la pieza completa |

Ambas filtran `status='published'`. Se registran en `backend/content/urls.py`.

El índice alfabético se arma en el frontend agrupando por la primera letra del título:
son pocas piezas y traerlas todas de una evita 27 peticiones. Si algún día crece,
`?letter=` ya está previsto.

### Admin

| Ruta | Vista |
|---|---|
| `GET/POST /api/admin/library/` | `AdminLibraryListCreateView` |
| `GET/PATCH/DELETE /api/admin/library/<pk>/` | `AdminLibraryDetailView` |

Se registran en `backend/content/admin_urls.py`. `IsAdminUser` + `MultiPartParser`
(entran portada y audio en el mismo formulario), igual que `AdminEventListCreateView`.

`DELETE` exige `status == 'trashed'`, como `AdminArticleDetailView.perform_destroy`:
el borrado definitivo siempre pasa primero por la papelera.

### Serializers

En `backend/content/serializers.py`, siguiendo el patrón camelCase del proyecto:

- `LibrarySerializer` (público): `coverImageUrl` y `audioUrl` absolutas vía
  `_absolute_file_url`; `author` y `narrator` anidados (nombre + slug/id), no solo el id.
- `LibraryAdminSerializer`: `coverImage` y `audio` como `FileField(write_only=True)`;
  `author` y `narrator` como ids.

### El paso que se olvida

`frontend/src/pages/api/admin-proxy/[...path].ts:10` tiene una lista blanca:

```
^(articles|authors|tags|regions|categories|events|media)(\/|$)
```

**Hay que agregar `library`.** Sin eso el panel da 404 aunque el backend esté perfecto.
Es lo que hoy deja a `Volume` sin panel.

## Frontend público

| Ruta | Muestra |
|---|---|
| `/biblioteca` | índice alfabético A–Z, título + autor + ▶ narrador, filtro por género |
| `/biblioteca/[slug]` | la pieza: portada, texto, `AudioPlayer`, autor, narrador, `source_note` |

Componentes nuevos:

- `components/content/LibraryIndex.astro` — las columnas por letra.
- `components/content/LibraryRow.astro` — la fila título/autor/narrador.

Se reusa tal cual `components/media/AudioPlayer.astro` (ya tiene su propio control de
avance y el backend ya sirve `Range`, ver `backend/config/media_views.py`).

Navegación: entrada "Biblioteca" en el menú público. El menú vive en
`components/layout/Header.astro` y `components/layout/MobileDrawer.astro`.

Buscador: `/buscar` hoy indexa solo artículos, filtrando en el cliente sobre la lista
completa. Se le suma un segundo pedido a `GET /api/library/` y las piezas se mezclan en
el mismo índice, cada una con una etiqueta visible "Biblioteca", para que nadie
confunda una obra ajena con una nota de la revista. Los filtros por categoría y
etiqueta siguen aplicando solo a los artículos: una pieza de biblioteca no tiene ni una
ni otra, así que al activar cualquiera de esos filtros las piezas se ocultan.

## Panel

Dos páginas, **no** un gestor inline tipo `EventManager`. El texto de una pieza necesita
el editor rico, que no entra en un formulario de una fila.

| Ruta | Copia de | Recorta |
|---|---|---|
| `/admin/biblioteca` | `pages/admin/index.astro` | — (listado con pestañas Activas/Papelera y buscador) |
| `/admin/biblioteca/[id]` | `pages/admin/publicaciones/[id].astro` | etiquetas, regiones, programación, YouTube/Spotify |

El editor lleva: título, autor (select), narrador (select, opcional), género (select),
texto (`RichTextEditor`), portada (`FileField`), audio (`FileField`), nota de origen.

Entrada nueva en el array `ITEMS` de `components/admin/AdminSidebar.astro:10-15`.

Cliente: `frontend/src/lib/library.ts` con `createPiece` / `updatePiece` /
`trashPiece` / `restorePiece` / `deletePiecePermanently`, siguiendo
`frontend/src/lib/publications.ts`.

Se reusan sin cambios: `FileField` (con su indicador de tamaño y proporción),
`RichTextEditor`, `lib/admin-dialog.ts`, el proxy autenticado y la optimización
automática de imágenes.

### Indicadores de tamaño

`FileField` acepta `recommendedSize`, `ratio` y `cropNote`. Para la Biblioteca:

- Portada: `1400 × 1400 px`, `1:1`, "No se recorta."
- Audio: "MP3, 96 kbps."

## Pruebas

Backend, en `backend/content/tests.py`, siguiendo `EventAdminTests`:

- El slug se genera y es único.
- El público solo ve `published`.
- `DELETE` sobre una pieza que no está en papelera devuelve 400.
- Borrar un narrador deja la pieza viva con `narrator = None`.
- Borrar un autor con piezas falla con 400 y mensaje claro (`PROTECT`).
- La portada se optimiza al guardar (ver `ArticleCoverOptimizationTests`).
- Filtro por `?genre=`.

Frontend, en `frontend/src/lib/`:

- `renderLiteraryMarkdown` conserva los saltos de verso.
- `renderMarkdown` (artículos) **no** los conserva — que el cambio no se filtre.
- Agrupación alfabética: títulos con tilde y con mayúscula/minúscula caen en la letra
  correcta; un título que empieza con número o comilla no rompe el índice.

## Fases

**Fase 1 — El Hacedor ya puede cargar todo.**
Modelo, migración, serializers, API pública y de admin, allowlist del proxy,
`renderLiteraryMarkdown`, las dos páginas del panel, `/biblioteca`,
`/biblioteca/[slug]`, entrada en los dos menús, pruebas.

**Fase 2 — Los lectores.**
`/lectores` con las fichas de los narradores y las piezas que narró cada uno. Sale casi
gratis porque `narrator` ya apunta a `Author`.

## Fuera de alcance

- Reproductor continuo tipo playlist.
- Descarga del audio.
- Transcripción automática.
- Buscador dentro del texto de las piezas (el global alcanza).

## Riesgo no técnico

Publicar íntegros a Vallejo, Pizarnik o Chocano son **derechos de autor**. Pizarnik
murió en 1972: su obra está protegida. El sitio del BBVA tiene los permisos
gestionados. El campo `source_note` sirve para acreditar la fuente, pero no reemplaza
el permiso. Conviene que El Hacedor lo resuelva antes de cargar el catálogo, no
después.
