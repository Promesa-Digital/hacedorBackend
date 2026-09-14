# El Hacedor — Backend

API de Django + DRF para el portal de literatura regional peruana. Backend
real del frontend en `../frontend` (Astro) — la integración
ya está hecha y verificada end-to-end (login + renovación de sesión, CRUD
de artículos, papelera + borrado permanente, orientación de portada
autodetectada, etiquetas, regiones, autores, newsletter, subida de
portada/audio).

## Contrato con el frontend

`lib/api.ts`, `lib/auth.ts`, `lib/publications.ts`, `lib/taxonomy.ts` y
`lib/newsletter.ts` del proyecto Astro hacen `fetch()` real contra los
endpoints de abajo. El JSON que devuelve la API ya está en camelCase con la
misma forma que las interfaces de `lib/types.ts`, así que los
componentes/páginas del frontend no necesitaron cambios — solo esos
archivos de `lib/`.

`lib/api.ts` corre en el frontmatter de Astro (server-side) y usa una
cuenta de servicio (`ADMIN_SERVICE_EMAIL`/`ADMIN_SERVICE_PASSWORD` en el
`.env` del frontend, nunca expuesta al navegador) para poder listar/leer
publicaciones de admin ahí. `lib/auth.ts`/`lib/publications.ts`/
`lib/taxonomy.ts` corren en el navegador con el JWT de la sesión real del
usuario logueado.

## Setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env          # ajustar si hace falta
python manage.py migrate
python manage.py seed_demo_data   # mismo contenido de demo que lib/api.ts tenía hardcodeado
python manage.py runserver 8001
```

Sin `.env`, corre en SQLite con CORS abierto solo a
`http://localhost:4321` (el puerto del Astro dev server). Para Postgres, ver
las variables `DB_*` en `.env.example`.

El comando de seed crea una cuenta exclusivamente para desarrollo local.
Nunca publique sus credenciales ni reutilice esa cuenta en producción.

## Endpoints públicos (sin auth)

| Método | Ruta | Equivalente en lib/api.ts |
|---|---|---|
| GET | `/api/articles/?category=&region=&tag=&page=&pageSize=` | `getArticles()` — responde `{items, total}` |
| GET | `/api/articles/<slug>/` | `getArticleBySlug()` |
| GET | `/api/articles/featured/?limit=` | `getFeaturedArticles()` |
| GET | `/api/articles/trending/?limit=` | `getTrendingArticles()` |
| GET | `/api/articles/<slug>/related/?limit=` | `getRelatedArticles()` |
| GET | `/api/regions/` | `getRegions()` |
| GET | `/api/regions/<code>/` | `getRegionByCode()` |
| GET | `/api/regions/<code>/authors/` | `getAuthorsByRegion()` |
| GET | `/api/volumes/` | `getVolumes()` |
| GET | `/api/tags/` | `getTags()` |
| GET | `/api/tags/<slug>/` | `getTagBySlug()` |
| GET | `/api/categories/` | `getCategories()` |
| GET | `/api/categories/<slug>/` | `getCategoryBySlug()` — incluye `featuredVideoUrl`/`featuredPodcastUrl`, elegidos a mano desde el panel (nunca adivinados de un artículo) |
| POST | `/api/newsletter/` `{email}` | `subscribeToNewsletter()` en `lib/newsletter.ts` — suscribirse dos veces con el mismo correo responde 200 `{email, alreadySubscribed: true}`, no un error |

## Endpoints de admin (JWT requerido)

| Método | Ruta | Equivalente en el frontend |
|---|---|---|
| POST | `/api/admin/login/` `{email, password}` → `{token, refreshToken, email}` | `login()` en `lib/auth.ts` |
| POST | `/api/admin/refresh/` `{refresh}` → `{access, refresh}` (SimpleJWT `TokenRefreshView`, `ROTATE_REFRESH_TOKENS=True`) | `refreshSession()` en `lib/auth.ts` — se llama sola desde `authFetch()` cuando un request responde 401 |
| GET | `/api/admin/articles/` (todos los status) | `getAllArticlesForAdmin()` |
| GET | `/api/admin/articles/<id>/` | `getArticleForAdminById()` |
| POST | `/api/admin/articles/` (multipart/form-data) | Creación desde el editor |
| PATCH | `/api/admin/articles/<id>/` (multipart/form-data) | `saveDraft()`/`submitPublication()` — "Guardar borrador"/"Programar"/"Publicar" son el mismo PATCH con distinto `status` |
| POST | `/api/admin/articles/<id>/trash/` | `trashPublication()` |
| POST | `/api/admin/articles/<id>/restore/` | `restorePublication()` (restaura a `draft`) |
| DELETE | `/api/admin/articles/<id>/` | `deleteArticlePermanently()` — borrado definitivo; el backend responde 400 si el artículo no está en `trashed` primero |
| GET/POST | `/api/admin/authors/` | GET: `getAuthorsForAdmin()` (puebla el `<select>` de autor del editor). POST: `addAuthor()` en `lib/taxonomy.ts` — panel "Autores", acepta multipart si se sube `avatar` |
| DELETE | `/api/admin/authors/<id>/` | `deleteAuthor()` — bloqueado (400) si el autor tiene artículos o volúmenes asociados (`on_delete=PROTECT`) |
| POST | `/api/admin/tags/` `{label}` | `addCustomTag()` |
| DELETE | `/api/admin/tags/<id>/` | `deleteTag()` |
| POST | `/api/admin/regions/` `{name, code}` | `addRegion()` en `lib/taxonomy.ts` |
| DELETE | `/api/admin/regions/<id>/` | `deleteRegion()` — `on_delete=SET_NULL` en `Article.region`/`Author.region`, así que nunca falla por referencias existentes |
| GET | `/api/admin/categories/` | Lista para la sección "Categorías" del panel |
| PATCH | `/api/admin/categories/<slug>/` `{featuredVideoUrl?, featuredPodcastUrl?}` | `updateCategoryMedia()` en `lib/taxonomy.ts` — únicos campos escribibles; `slug`/`label`/`colorVariant` son `read_only` a propósito (atados a una ruta fija del frontend) |

Todas las rutas de admin van con `Authorization: Bearer <token>`.

`coverImageOrientation` **no se manda desde el frontend**: `Article.save()`
la calcula sola con Pillow a partir del ancho/alto real de `coverImage` en
cada guardado (ver `content/models.py`). El campo sigue siendo `read_only`
en `ArticleAdminSerializer` a propósito.

`youtubeEmbedUrl`/`spotifyEmbedUrl` (en `Article` y `featuredVideoUrl`/
`featuredPodcastUrl` en `Category`) aceptan **cualquier formato de link**
que el editor pegue tal cual lo copia del navegador
(`youtube.com/watch?v=...`, `youtu.be/...`, un link normal de
`open.spotify.com/track|episode/...`) — `content/embeds.py` los normaliza
al único formato embebible en un `<iframe>` (`/embed/...`) en
`Article.save()`/`Category.save()`. Sin esto, el navegador tira "refused to
connect" porque YouTube/Spotify bloquean sus páginas normales dentro de un
iframe (`X-Frame-Options`).

Los POST/PATCH de `/api/admin/articles/` aceptan **multipart/form-data**
(no JSON) porque `coverImage`/`narrationAudio` son archivos. Todos los
demás campos (`title`, `excerpt`, `body`, `category`, `author`, `tags`
repetido por cada etiqueta, `youtubeEmbedUrl`, `spotifyEmbedUrl`, `status`,
`scheduledFor`) van como campos de texto normales del mismo form-data — DRF
los parsea igual que si fuera JSON. `tags` y `coverImage`/`narrationAudio`
son opcionales; si no se manda un archivo nuevo, la portada/audio actual no
se toca.

## Notas técnicas / cosas que costó descubrir

- **DRF exige que todo campo declarado esté en `Meta.fields`.** Si agregás
  un campo nuevo a un serializer (por ejemplo `coverImage` en
  `ArticleAdminSerializer`) y se te olvida sumarlo también a `Meta.fields`,
  DRF tira `AssertionError` en cuanto se instancia el serializer — no es un
  error de sintaxis, se descubre recién al primer request. `content/serializers.py`
  ya lo tiene bien, pero es fácil repetir el error si se agregan más campos.
- **MultiPartParser ya viene por defecto** en `DEFAULT_PARSER_CLASSES` de
  DRF — no hizo falta configurar nada en `settings.py` para aceptar
  multipart/form-data, ya funcionaba.
- **El frontend Astro usa `export const prerender = false`** en
  `articulo/[slug].astro`, `etiquetas/[tag].astro`, `404.astro`,
  `admin/index.astro`, `admin/autores.astro`,
  `admin/etiquetas-categorias.astro` y `admin/publicaciones/[id].astro`
  para que el contenido creado desde este backend (publicaciones, autores,
  etiquetas/regiones/categorías) tenga página propia sin rebuild. Si
  cambiás cuál backend corre en qué puerto, o movés el sitio a otro host,
  revisá `PUBLIC_API_URL` en el `.env` del frontend.
- **`?limit=` en `ArticleFeaturedView`/`ArticleTrendingView`/`ArticleRelatedView`
  se valida con `_parse_limit()`** (`content/views.py`), no con `int()` a
  pelo — un valor no numérico (`?limit=abc`) tiraba `ValueError` sin
  capturar y devolvía 500 con traceback en vez de un 400 normal. Si se
  agrega un endpoint nuevo con un query param parecido, usar ese mismo
  helper en vez de repetir el `int()` directo.
- **`Article.reading_time_minutes` se recalcula en cada `save()` si hay
  `body`, sin condición.** Antes solo se recalculaba cuando el campo valía
  exactamente `1` (el default) — como es `read_only` en el serializer y el
  cliente nunca lo manda, en cuanto el primer cálculo daba otro valor
  quedaba congelado para siempre (editar el body de 1000 a 4000 palabras no
  cambiaba el tiempo de lectura ya guardado). Ojo si se reintroduce algo
  así "para no pisar un valor manual": no hay forma de mandar un valor
  manual desde la API, así que esa condición nunca protegía nada real.

## Tests

```bash
python manage.py test
```

44 tests (`accounts/tests.py`, `content/tests.py`) sobre una base de datos
de prueba aparte (se crea y destruye sola, nunca toca `db.sqlite3`):
login/refresh, CRUD de artículos de admin, papelera + restaurar + borrado
permanente, orientación de portada autodetectada (sube imágenes reales de
prueba con Pillow), CRUD de autores (incluyendo el bloqueo de borrado por
`on_delete=PROTECT`), tags, regiones, video/podcast destacado por categoría
(incluye la regresión de slug/label quedando de solo lectura), normalización
de URLs de YouTube/Spotify, y newsletter.

## Pendiente / decisiones abiertas

- **Categorías**: son un modelo real (`content.Category`) administrable
  desde `/admin/`, pero el frontend Astro tiene una ruta de archivo fija por
  categoría (`/critica-literaria`, `/entrevistas`...). Agregar una categoría
  acá no crea una página nueva sola — requiere coordinar con el frontend. No
  se construyó un endpoint público de categorías porque nada lo consume
  todavía.
- **Autenticación**: no hay "olvidé mi contraseña" ni forma de crear otro
  usuario editorial desde el panel — solo por `/admin/` de Django o
  `manage.py shell`. Un flujo de recuperación por correo necesita decidir
  primero qué proveedor de SMTP se va a usar; no se armó a medias sin esa
  decisión.
- **Producción**: `python manage.py check --deploy` señala lo esperable de
  un proyecto recién creado (`DEBUG=True`, `SECRET_KEY` de desarrollo, sin
  HTTPS/HSTS) — hay que resolverlo en el `.env` del entorno de despliegue,
  no en código.
  El adaptador SSR del frontend (`@astrojs/node`, ver
  `astro.config.mjs` en `../frontend`) ya está resuelto y
  probado con `astro build` real — las rutas on-demand no dependen más de
  `astro dev`.
