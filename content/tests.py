import io
import tempfile
from pathlib import Path as PathLib
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .admin_views import AdminInlineImageUploadView
from .images import optimizar_bytes, optimizar_imagen
from .embeds import normalize_spotify_embed_url, normalize_youtube_embed_url
from .models import Article, Author, Category, Event, LibraryPiece, NewsletterSubscriber, Region, Tag


class EmbedNormalizationTests(SimpleTestCase):
    def test_youtube_watch_url(self):
        self.assertEqual(
            normalize_youtube_embed_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
        )

    def test_youtube_short_url_with_extra_params(self):
        self.assertEqual(
            normalize_youtube_embed_url('https://youtu.be/dQw4w9WgXcQ?t=30'),
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
        )

    def test_youtube_embed_url_is_left_as_is(self):
        self.assertEqual(
            normalize_youtube_embed_url('https://www.youtube.com/embed/dQw4w9WgXcQ'),
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
        )

    def test_youtube_empty_string(self):
        self.assertEqual(normalize_youtube_embed_url(''), '')

    def test_spotify_regular_url(self):
        self.assertEqual(
            normalize_spotify_embed_url('https://open.spotify.com/episode/1a2B3c4D5e6F7g8H9i0J?si=x'),
            'https://open.spotify.com/embed/episode/1a2B3c4D5e6F7g8H9i0J',
        )

    def test_spotify_empty_string(self):
        self.assertEqual(normalize_spotify_embed_url(''), '')


def make_image_file(width, height, name='cover.jpg'):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), color='red').save(buffer, format='JPEG')
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type='image/jpeg')


# Las pruebas suben imágenes de verdad, y sin esto quedaban guardadas en el
# media/ del proyecto: 307 archivos en disco contra 11 referenciados por la base.
# Cada corrida dejaba decenas de huérfanos que nadie iba a borrar nunca.
# Con un directorio temporal, el sistema operativo se encarga.
# Path y no el texto que devuelve mkdtemp: el MEDIA_ROOT real es un Path y hay
# pruebas que hacen `settings.MEDIA_ROOT / 'inline'`. Con un str eso revienta.
MEDIA_DE_PRUEBA = PathLib(tempfile.mkdtemp(prefix='elhacedor-tests-'))


@override_settings(MEDIA_ROOT=MEDIA_DE_PRUEBA)
class AdminAPITestCase(APITestCase):
    """Base con un usuario admin autenticado vía Bearer y taxonomía mínima.

    El MEDIA_ROOT temporal se hereda en las subclases: Django aplica el
    `override_settings` del padre a todo lo que cuelgue de él.
    """

    def setUp(self):
        # El limitador de tasa del login (60/minuto) cuenta en la caché, que en
        # las pruebas es de proceso y sobrevive de un test al siguiente. Cada
        # prueba de admin hace su login acá, así que pasadas las 60 el resto de
        # la suite fallaba con un KeyError: 'token' desconcertante — el login
        # devolvía 429 y nadie lo miraba. Limpiarla deja cada prueba
        # independiente del orden y de cuántas haya.
        cache.clear()
        User.objects.create_user(username='editor', email='editor@elhacedor.pe', password='clave-segura', is_staff=True)
        login = self.client.post('/api/admin/login/', {'email': 'editor@elhacedor.pe', 'password': 'clave-segura'}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["token"]}')

        self.category = Category.objects.create(slug='articulos', label='Artículos', color_variant='primary')
        self.author = Author.objects.create(name='Autora de prueba')
        self.region = Region.objects.create(name='Región Test', code='999')


class ArticleAdminCRUDTests(AdminAPITestCase):
    def test_create_requires_authentication(self):
        self.client.credentials()
        res = self.client.post(
            '/api/admin/articles/',
            {'title': 'x', 'excerpt': 'x', 'body': 'x', 'category': self.category.slug, 'author': self.author.id, 'status': 'draft'},
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_draft_is_not_exposed_by_public_detail(self):
        article = Article.objects.create(title='Privado', slug='privado', excerpt='x', body='x', category=self.category, author=self.author, status='draft', published_at=timezone.now())
        self.client.credentials()
        res = self.client.get(f'/api/articles/{article.slug}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_article(self):
        res = self.client.post(
            '/api/admin/articles/',
            {
                'title': 'Artículo de prueba',
                'excerpt': 'Resumen',
                'body': 'Cuerpo',
                'category': self.category.slug,
                'author': self.author.id,
                'status': 'draft',
            },
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['title'], 'Artículo de prueba')
        self.assertEqual(res.data['status'], 'draft')

    def test_duplicate_titles_receive_unique_slugs(self):
        payload = {'title': 'Título repetido', 'excerpt': 'x', 'body': 'x', 'category': self.category.slug, 'author': self.author.id, 'status': 'draft'}
        first = self.client.post('/api/admin/articles/', payload, format='json')
        second = self.client.post('/api/admin/articles/', payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(first.data['slug'], second.data['slug'])

    def test_rejects_non_youtube_embed_url(self):
        res = self.client.post('/api/admin/articles/', {
            'title': 'Embed inseguro', 'excerpt': 'x', 'body': 'x', 'category': self.category.slug,
            'author': self.author.id, 'status': 'draft', 'youtubeEmbedUrl': 'javascript:alert(1)',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('youtubeEmbedUrl', res.data)

    def test_create_article_normalizes_pasted_youtube_watch_url(self):
        res = self.client.post(
            '/api/admin/articles/',
            {
                'title': 'Con video',
                'excerpt': 'x',
                'body': 'x',
                'category': self.category.slug,
                'author': self.author.id,
                'status': 'draft',
                'youtubeEmbedUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            },
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['youtubeEmbedUrl'], 'https://www.youtube.com/embed/dQw4w9WgXcQ')

    def test_create_article_with_region_appears_in_public_region_filter(self):
        res = self.client.post(
            '/api/admin/articles/',
            {
                'title': 'Con región',
                'excerpt': 'x',
                'body': 'x',
                'category': self.category.slug,
                'author': self.author.id,
                'status': 'published',
                'region': self.region.id,
            },
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['region']['code'], '999')

        list_res = self.client.get(f'/api/articles/?region={self.region.code}')
        self.assertEqual(list_res.data['total'], 1)

    def test_landscape_cover_image_orientation_autodetected(self):
        res = self.client.post(
            '/api/admin/articles/',
            {
                'title': 'Landscape',
                'excerpt': 'x',
                'body': 'x',
                'category': self.category.slug,
                'author': self.author.id,
                'status': 'draft',
                'coverImage': make_image_file(600, 300),
            },
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['coverImageOrientation'], 'landscape')

    def test_portrait_cover_image_orientation_autodetected(self):
        res = self.client.post(
            '/api/admin/articles/',
            {
                'title': 'Portrait',
                'excerpt': 'x',
                'body': 'x',
                'category': self.category.slug,
                'author': self.author.id,
                'status': 'draft',
                'coverImage': make_image_file(300, 600),
            },
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['coverImageOrientation'], 'portrait')

    def test_square_cover_image_orientation_autodetected(self):
        res = self.client.post(
            '/api/admin/articles/',
            {
                'title': 'Square',
                'excerpt': 'x',
                'body': 'x',
                'category': self.category.slug,
                'author': self.author.id,
                'status': 'draft',
                'coverImage': make_image_file(400, 400),
            },
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['coverImageOrientation'], 'square')


class ArticleTrashRestoreDeleteTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        self.article = Article.objects.create(
            title='Para papelera',
            slug='para-papelera',
            excerpt='x',
            body='x',
            category=self.category,
            author=self.author,
            published_at=timezone.now(),
            status='published',
        )

    def test_trash_sets_status(self):
        res = self.client.post(f'/api/admin/articles/{self.article.id}/trash/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.article.refresh_from_db()
        self.assertEqual(self.article.status, 'trashed')

    def test_restore_sets_status_to_draft(self):
        self.article.status = 'trashed'
        self.article.save(update_fields=['status'])
        res = self.client.post(f'/api/admin/articles/{self.article.id}/restore/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.article.refresh_from_db()
        self.assertEqual(self.article.status, 'draft')

    def test_permanent_delete_blocked_unless_trashed(self):
        res = self.client.delete(f'/api/admin/articles/{self.article.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Article.objects.filter(pk=self.article.pk).exists())

    def test_permanent_delete_allowed_once_trashed(self):
        self.article.status = 'trashed'
        self.article.save(update_fields=['status'])
        res = self.client.delete(f'/api/admin/articles/{self.article.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Article.objects.filter(pk=self.article.pk).exists())


class AuthorAdminTests(AdminAPITestCase):
    def test_list_requires_auth(self):
        self.client.credentials()
        res = self.client.get('/api/admin/authors/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_lists_authors(self):
        res = self.client.get('/api/admin/authors/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(any(a['name'] == self.author.name for a in res.data))

    def test_create_author(self):
        res = self.client.post('/api/admin/authors/', {'name': 'Autor Nuevo', 'bio': 'Bio de prueba'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['name'], 'Autor Nuevo')
        self.assertIsNone(res.data['region'])

    def test_create_author_with_region(self):
        res = self.client.post('/api/admin/authors/', {'name': 'Autora Regional', 'region': self.region.id}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['region'], self.region.name)

    def test_create_author_requires_auth(self):
        self.client.credentials()
        res = self.client.post('/api/admin/authors/', {'name': 'Sin sesión'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_author_without_content(self):
        author = Author.objects.create(name='Autor Borrable')
        res = self.client.delete(f'/api/admin/authors/{author.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Author.objects.filter(pk=author.pk).exists())

    def test_delete_author_with_articles_is_blocked(self):
        Article.objects.create(
            title='Escrito por este autor',
            slug='escrito-por-este-autor',
            excerpt='x',
            body='x',
            category=self.category,
            author=self.author,
            published_at=timezone.now(),
            status='published',
        )
        res = self.client.delete(f'/api/admin/authors/{self.author.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', res.data)
        self.assertTrue(Author.objects.filter(pk=self.author.pk).exists())


class AuthorUpdateTests(AdminAPITestCase):
    """PATCH /api/admin/authors/<id>/ — la edición por fila del panel.

    El cliente reportó que un autor se cargaba una vez y después no se podía
    tocar más: la bio con un error de tipeo quedaba así para siempre, porque la
    única acción de la fila era "Eliminar" y el borrado encima lo bloquea el
    PROTECT en cuanto el autor tiene una publicación.
    """

    def test_sin_autenticacion_devuelve_401(self):
        self.client.credentials()
        respuesta = self.client.patch(f'/api/admin/authors/{self.author.id}/', {'bio': 'Colada'}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_401_UNAUTHORIZED)
        self.author.refresh_from_db()
        self.assertEqual(self.author.bio, '')

    def test_edita_la_bio(self):
        respuesta = self.client.patch(
            f'/api/admin/authors/{self.author.id}/',
            {'bio': 'Narradora arequipeña. Publicó dos libros de cuentos.'},
            format='json',
        )
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertEqual(respuesta.data['bio'], 'Narradora arequipeña. Publicó dos libros de cuentos.')
        self.author.refresh_from_db()
        self.assertEqual(self.author.bio, 'Narradora arequipeña. Publicó dos libros de cuentos.')

    def test_edita_nombre_bio_y_region_en_un_solo_envio(self):
        respuesta = self.client.patch(
            f'/api/admin/authors/{self.author.id}/',
            {'name': 'Autora Corregida', 'bio': 'Bio nueva', 'region': self.region.id},
            format='json',
        )
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        # La región sale como nombre, no como id: misma forma de lectura que el alta.
        self.assertEqual(respuesta.data['region'], self.region.name)
        self.author.refresh_from_db()
        self.assertEqual(self.author.name, 'Autora Corregida')
        self.assertEqual(self.author.region, self.region)

    def test_se_le_puede_quitar_la_region(self):
        self.author.region = self.region
        self.author.save(update_fields=['region'])

        respuesta = self.client.patch(f'/api/admin/authors/{self.author.id}/', {'region': None}, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIsNone(respuesta.data['region'])
        self.author.refresh_from_db()
        self.assertIsNone(self.author.region)

    def test_una_region_vacia_en_multipart_desasigna(self):
        # El panel manda el formulario como multipart (por el avatar) y un
        # FormData no sabe expresar `null`: la región sin elegir viaja como
        # cadena vacía. Si esto dejara de traducirse a null, "Sin región" en el
        # desplegable guardaría la región anterior sin avisar.
        self.author.region = self.region
        self.author.save(update_fields=['region'])

        respuesta = self.client.patch(
            f'/api/admin/authors/{self.author.id}/',
            {'name': self.author.name, 'bio': 'x', 'region': ''},
            format='multipart',
        )

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIsNone(respuesta.data['region'])
        self.author.refresh_from_db()
        self.assertIsNone(self.author.region)

    def test_un_nombre_vacio_se_rechaza(self):
        respuesta = self.client.patch(f'/api/admin/authors/{self.author.id}/', {'name': '   '}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', respuesta.data)
        self.author.refresh_from_db()
        self.assertEqual(self.author.name, 'Autora de prueba')

    def test_una_region_inexistente_se_rechaza(self):
        respuesta = self.client.patch(f'/api/admin/authors/{self.author.id}/', {'region': 999999}, format='json')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('region', respuesta.data)

    def test_reemplazar_el_avatar_borra_el_anterior(self):
        primera = self.client.patch(
            f'/api/admin/authors/{self.author.id}/',
            {'avatar': SimpleUploadedFile('foto.jpg', _imagen_bytes(400, 400), content_type='image/jpeg')},
            format='multipart',
        )
        self.assertEqual(primera.status_code, status.HTTP_200_OK)
        self.author.refresh_from_db()
        ruta_anterior = self.author.avatar.name
        self.assertTrue(default_storage.exists(ruta_anterior))

        segunda = self.client.patch(
            f'/api/admin/authors/{self.author.id}/',
            {'avatar': SimpleUploadedFile('otra.jpg', _imagen_bytes(300, 300), content_type='image/jpeg')},
            format='multipart',
        )

        self.assertEqual(segunda.status_code, status.HTTP_200_OK)
        self.author.refresh_from_db()
        self.assertNotEqual(self.author.avatar.name, ruta_anterior)
        # Sin el update() del serializer esto dejaba un huérfano en media/authors/.
        self.assertFalse(default_storage.exists(ruta_anterior))

    def test_se_puede_editar_un_autor_con_publicaciones(self):
        # El caso que hacía imposible corregir nada: con una publicación
        # asociada, el DELETE devuelve 400 por el PROTECT, así que "borrar y
        # cargar de nuevo" tampoco era una salida.
        Article.objects.create(
            title='Escrito por esta autora',
            slug='escrito-por-esta-autora',
            excerpt='x',
            body='x',
            category=self.category,
            author=self.author,
            published_at=timezone.now(),
            status='published',
        )

        respuesta = self.client.patch(f'/api/admin/authors/{self.author.id}/', {'bio': 'Bio al día'}, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.author.refresh_from_db()
        self.assertEqual(self.author.bio, 'Bio al día')


class TagAdminTests(AdminAPITestCase):
    def test_create_tag(self):
        res = self.client.post('/api/admin/tags/', {'label': 'Nueva etiqueta'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['label'], 'Nueva etiqueta')

    def test_create_tag_requires_label(self):
        res = self.client.post('/api/admin/tags/', {'label': ''}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_tag(self):
        tag = Tag.objects.create(label='Borrable')
        res = self.client.delete(f'/api/admin/tags/{tag.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Tag.objects.filter(pk=tag.pk).exists())

    def test_case_insensitive_labels_receive_unique_slugs(self):
        first = self.client.post('/api/admin/tags/', {'label': 'Etiqueta Audit'}, format='json')
        second = self.client.post('/api/admin/tags/', {'label': 'etiqueta audit'}, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(first.data['slug'], second.data['slug'])


class RegionAdminTests(AdminAPITestCase):
    def test_create_region(self):
        res = self.client.post('/api/admin/regions/', {'name': 'Tacna', 'code': '230'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_duplicate_code_rejected(self):
        res = self.client.post('/api/admin/regions/', {'name': 'Otra', 'code': self.region.code}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_region_nulls_out_article_region(self):
        article = Article.objects.create(
            title='Con región',
            slug='con-region',
            excerpt='x',
            body='x',
            category=self.category,
            author=self.author,
            region=self.region,
            published_at=timezone.now(),
            status='published',
        )
        res = self.client.delete(f'/api/admin/regions/{self.region.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        article.refresh_from_db()
        self.assertIsNone(article.region)


class CategoryPublicTests(APITestCase):
    def test_list_and_detail(self):
        Category.objects.create(slug='entrevistas', label='Entrevistas', featured_video_url='https://youtube.com/embed/x')
        list_res = self.client.get('/api/categories/')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertTrue(any(c['slug'] == 'entrevistas' for c in list_res.data))

        detail_res = self.client.get('/api/categories/entrevistas/')
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.data['featuredVideoUrl'], 'https://youtube.com/embed/x')


class CategoryAdminTests(AdminAPITestCase):
    def test_list_requires_auth(self):
        self.client.credentials()
        res = self.client.get('/api/admin/categories/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_featured_video_and_podcast(self):
        res = self.client.patch(
            f'/api/admin/categories/{self.category.slug}/',
            {'featuredVideoUrl': 'https://youtube.com/embed/abcdef', 'featuredPodcastUrl': 'https://open.spotify.com/embed/episode/abc123'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['featuredVideoUrl'], 'https://www.youtube.com/embed/abcdef')
        self.assertEqual(res.data['featuredPodcastUrl'], 'https://open.spotify.com/embed/episode/abc123')

    def test_rejects_arbitrary_embed_hosts(self):
        res = self.client.patch(
            f'/api/admin/categories/{self.category.slug}/',
            {'featuredVideoUrl': 'https://attacker.example/embed/video'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('featuredVideoUrl', res.data)

    def test_update_normalizes_pasted_youtube_watch_url(self):
        res = self.client.patch(
            f'/api/admin/categories/{self.category.slug}/',
            {'featuredVideoUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['featuredVideoUrl'], 'https://www.youtube.com/embed/dQw4w9WgXcQ')

    def test_slug_and_label_stay_read_only(self):
        """Regresión: slug/label no tienen read_only explícito propio y por
        default un ModelSerializer los deja escribibles con solo listarlos en
        Meta.fields — sin este override, un PATCH podía cambiar el slug de
        una categoría fija y romper la ruta del frontend que depende de él."""
        res = self.client.patch(
            f'/api/admin/categories/{self.category.slug}/',
            {'slug': 'otra-cosa', 'label': 'Otro label'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.category.refresh_from_db()
        self.assertEqual(self.category.slug, 'articulos')
        self.assertEqual(self.category.label, 'Artículos')


class NewsletterTests(APITestCase):
    def test_subscribe_new_email(self):
        res = self.client.post('/api/newsletter/', {'email': 'lector@example.com'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(NewsletterSubscriber.objects.filter(email='lector@example.com').exists())

    def test_subscribe_duplicate_email_is_not_an_error(self):
        NewsletterSubscriber.objects.create(email='lector@example.com')
        res = self.client.post('/api/newsletter/', {'email': 'lector@example.com'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['alreadySubscribed'])

    def test_subscribe_invalid_email_rejected(self):
        res = self.client.post('/api/newsletter/', {'email': 'no-es-un-correo'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class PublicArticleEdgeCaseTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(slug='articulos', label='Artículos')
        self.author = Author.objects.create(name='Autora')

    def test_negative_and_excessive_limits_are_rejected(self):
        self.assertEqual(self.client.get('/api/articles/featured/?limit=-1').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.client.get('/api/articles/featured/?limit=101').status_code, status.HTTP_400_BAD_REQUEST)

    def test_due_scheduled_article_is_promoted_and_public(self):
        article = Article.objects.create(
            title='Ya programado', excerpt='x', body='x', category=self.category, author=self.author,
            published_at=timezone.now(), scheduled_for=timezone.now() - timezone.timedelta(minutes=1), status='scheduled',
        )
        response = self.client.get(f'/api/articles/{article.slug}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        article.refresh_from_db()
        self.assertEqual(article.status, 'published')

    def test_draft_related_endpoint_is_not_enumerable(self):
        article = Article.objects.create(
            title='Borrador secreto', excerpt='x', body='x', category=self.category, author=self.author,
            published_at=timezone.now(), status='draft',
        )
        self.assertEqual(self.client.get(f'/api/articles/{article.slug}/related/').status_code, status.HTTP_404_NOT_FOUND)

    def test_has_narration_tracks_audio_presence(self):
        article = Article.objects.create(
            title='Sin audio', excerpt='x', body='x', category=self.category, author=self.author,
            published_at=timezone.now(), has_narration=True, narration_audio=None,
        )
        article.refresh_from_db()
        self.assertFalse(article.has_narration)


class EventPublicTests(APITestCase):
    def setUp(self):
        self.published = Event.objects.create(
            title='Conversatorio de narrativa andina',
            description='Mesa redonda con autores de la región.',
            starts_at=timezone.now() + timezone.timedelta(days=10),
            location='Biblioteca Municipal, Arequipa',
            status='published',
        )
        Event.objects.create(
            title='Evento todavía sin confirmar',
            starts_at=timezone.now() + timezone.timedelta(days=20),
            status='draft',
        )

    def test_list_only_returns_published(self):
        res = self.client.get('/api/events/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['title'], 'Conversatorio de narrativa andina')

    def test_public_payload_is_camel_case_and_hides_status(self):
        res = self.client.get('/api/events/')
        item = res.data[0]
        self.assertIn('startsAt', item)
        self.assertIn('coverImageUrl', item)
        self.assertIn('externalUrl', item)
        self.assertNotIn('status', item)
        self.assertNotIn('starts_at', item)

    def test_slug_is_generated_from_title(self):
        self.assertEqual(self.published.slug, 'conversatorio-de-narrativa-andina')

    def test_slug_collision_gets_suffix(self):
        other = Event.objects.create(
            title='Conversatorio de narrativa andina',
            starts_at=timezone.now(),
            status='published',
        )
        self.assertNotEqual(other.slug, self.published.slug)


class EventAdminTests(AdminAPITestCase):
    def test_list_requires_authentication(self):
        self.client.credentials()
        res = self.client.get('/api/admin/events/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_and_list_includes_drafts(self):
        res = self.client.post(
            '/api/admin/events/',
            {
                'title': 'Taller de crónica',
                'description': 'Cuatro sesiones.',
                'startsAt': '2026-11-02T18:30:00-05:00',
                'location': 'Casa de la Cultura, Cusco',
                'status': 'draft',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['title'], 'Taller de crónica')
        self.assertEqual(res.data['status'], 'draft')

        listed = self.client.get('/api/admin/events/')
        self.assertEqual(len(listed.data), 1)
        # El borrador no sale en el endpoint público
        self.assertEqual(len(self.client.get('/api/events/').data), 0)

    def test_starts_at_is_required(self):
        res = self.client.post('/api/admin/events/', {'title': 'Sin fecha'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('startsAt', res.data)

    def test_patch_publishes_a_draft(self):
        event = Event.objects.create(title='Borrador', starts_at=timezone.now(), status='draft')
        res = self.client.patch(f'/api/admin/events/{event.id}/', {'status': 'published'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertEqual(event.status, 'published')

    def test_delete_removes_the_event(self):
        event = Event.objects.create(title='A borrar', starts_at=timezone.now(), status='published')
        res = self.client.delete(f'/api/admin/events/{event.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Event.objects.filter(pk=event.pk).exists())


class InlineImageUploadTests(AdminAPITestCase):
    """POST /api/admin/media/ — imágenes que van DENTRO del cuerpo del artículo.

    Este endpoint recibe archivos arbitrarios de quien edita y devuelve una URL
    que después se publica en el sitio, así que los casos de abajo no son
    decoración: cada uno tapa una forma conocida de convertir una subida en
    ejecución de código en el navegador de quien lee.
    """

    URL = '/api/admin/media/'

    def test_requires_authentication(self):
        self.client.credentials()
        res = self.client.post(self.URL, {'file': make_image_file(10, 10)}, format='multipart')
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_uploads_image_and_returns_absolute_url(self):
        res = self.client.post(self.URL, {'file': make_image_file(40, 30)}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['url'].startswith('http'))
        self.assertIn('/media/inline/', res.data['url'])

    def test_rejects_missing_file(self):
        res = self.client.post(self.URL, {}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_svg_because_it_can_carry_scripts(self):
        svg = SimpleUploadedFile(
            'malicioso.svg',
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type='image/svg+xml',
        )
        res = self.client.post(self.URL, {'file': svg}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_file_that_only_pretends_to_be_an_image(self):
        """El content-type lo elige el cliente y se puede mentir; lo que manda
        es que Pillow pueda abrir el archivo de verdad."""
        fake = SimpleUploadedFile('trampa.jpg', b'<?php system($_GET["c"]); ?>', content_type='image/jpeg')
        res = self.client.post(self.URL, {'file': fake}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_file_over_the_size_limit(self):
        """Se baja el tope en vez de fabricar un archivo de 6 MB: pisarle `.size`
        al SimpleUploadedFile no sirve, porque Django rearma el objeto al parsear
        el multipart y vuelve a medir el archivo real."""
        with patch.object(AdminInlineImageUploadView, 'MAX_BYTES', 100):
            res = self.client.post(self.URL, {'file': make_image_file(40, 30)}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('MB', str(res.data))

    def test_ignores_the_filename_sent_by_the_client(self):
        """Un nombre venido de afuera puede traer barras o '..' para escribir
        fuera de MEDIA_ROOT. El nombre lo decide el servidor."""
        res = self.client.post(
            self.URL,
            {'file': make_image_file(10, 10, name='../../../etc/passwd.jpg')},
            format='multipart',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('..', res.data['url'])
        self.assertNotIn('passwd', res.data['url'])


@override_settings(MEDIA_ROOT=MEDIA_DE_PRUEBA)
class MediaRangeRequestTests(APITestCase):
    """Entrega de archivos subidos por tramos (HTTP Range).

    Django 6 no implementa Range en ninguna parte, así que devolvía siempre el
    archivo entero: un reproductor de audio adelanta pidiendo un tramo de bytes,
    y al recibir todo desde el principio la barra de progreso no se podía mover.
    Estos casos fijan que el tramo se respete y que los bytes sean los correctos.
    """

    def setUp(self):
        from django.conf import settings

        self.contenido = bytes(range(256)) * 40  # 10240 bytes reconocibles
        self.carpeta = settings.MEDIA_ROOT / 'inline'
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.archivo = self.carpeta / 'rango-de-prueba.bin'
        self.archivo.write_bytes(self.contenido)
        self.url = '/media/inline/rango-de-prueba.bin'

    def tearDown(self):
        self.archivo.unlink(missing_ok=True)

    def test_anuncia_que_acepta_tramos(self):
        """Sin este encabezado el navegador ni intenta adelantar."""
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers['Accept-Ranges'], 'bytes')

    def test_devuelve_el_tramo_pedido(self):
        res = self.client.get(self.url, headers={'range': 'bytes=1000-1999'})
        self.assertEqual(res.status_code, 206)
        self.assertEqual(res.headers['Content-Range'], f'bytes 1000-1999/{len(self.contenido)}')
        self.assertEqual(b''.join(res.streaming_content), self.contenido[1000:2000])

    def test_tramo_abierto_llega_hasta_el_final(self):
        res = self.client.get(self.url, headers={'range': 'bytes=10000-'})
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), self.contenido[10000:])

    def test_tramo_por_el_final(self):
        res = self.client.get(self.url, headers={'range': 'bytes=-100'})
        self.assertEqual(res.status_code, 206)
        self.assertEqual(b''.join(res.streaming_content), self.contenido[-100:])

    def test_tramo_imposible_responde_416(self):
        res = self.client.get(self.url, headers={'range': 'bytes=999999-'})
        self.assertEqual(res.status_code, 416)
        self.assertEqual(res.headers['Content-Range'], f'bytes */{len(self.contenido)}')

    def test_un_range_ilegible_devuelve_el_archivo_entero(self):
        """Mejor mandar todo —que es una respuesta válida— que fallar."""
        res = self.client.get(self.url, headers={'range': 'paginas=1-2'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(b''.join(res.streaming_content), self.contenido)

    def test_sin_range_el_archivo_llega_completo(self):
        res = self.client.get(self.url)
        self.assertEqual(b''.join(res.streaming_content), self.contenido)

    def test_sigue_sin_poder_salir_de_media_root(self):
        res = self.client.get('/media/..%2fconfig/settings.py')
        self.assertIn(res.status_code, (400, 404))


def _imagen_bytes(ancho, alto, formato='JPEG', exif_orientacion=None, modo='RGB'):
    """Genera una imagen de prueba con ruido, para que comprima como una foto
    real y no como un rectángulo de color plano (que pesaría casi nada y haría
    pasar los tests de peso por el motivo equivocado)."""
    import random

    random.seed(ancho * alto)
    imagen = Image.new(modo, (ancho, alto))
    canales = len(imagen.getbands())
    if canales == 1:
        imagen.putdata([random.randrange(256) for _ in range(ancho * alto)])
    else:
        imagen.putdata([tuple(random.randrange(256) for _ in range(canales)) for _ in range(ancho * alto)])

    guardado = {}
    if exif_orientacion is not None:
        exif = imagen.getexif()
        exif[274] = exif_orientacion
        guardado['exif'] = exif
    buffer = io.BytesIO()
    imagen.save(buffer, formato, **guardado)
    return buffer.getvalue()


class OptimizarImagenTests(SimpleTestCase):
    """La optimización corre en cada save(), así que además de achicar tiene
    que ser idempotente: si volviera a reencodar una imagen ya procesada, cada
    edición del artículo degradaría un poco más la portada."""

    def test_achica_hasta_el_lado_mayor(self):
        datos = _imagen_bytes(4000, 3000)
        resultado = optimizar_bytes(datos)

        self.assertIsNotNone(resultado)
        nuevos, formato = resultado
        self.assertEqual(formato, 'WEBP')
        self.assertEqual(Image.open(io.BytesIO(nuevos)).size, (2400, 1800))
        self.assertLess(len(nuevos), len(datos))

    def test_no_agranda_una_imagen_chica(self):
        datos = _imagen_bytes(800, 600)
        resultado = optimizar_bytes(datos)

        if resultado is not None:
            nuevos, _ = resultado
            self.assertEqual(Image.open(io.BytesIO(nuevos)).size, (800, 600))
            self.assertLessEqual(len(nuevos), len(datos))

    def test_es_idempotente(self):
        primera, _ = optimizar_bytes(_imagen_bytes(4000, 3000))
        self.assertIsNone(optimizar_bytes(primera))

    def test_aplica_la_rotacion_exif(self):
        # Una foto vertical de celular: se guarda apaisada más la marca 6
        # ("rotar 90"). El navegador la muestra vertical, así que el archivo
        # tiene que quedar vertical de verdad.
        datos = _imagen_bytes(4000, 3000, exif_orientacion=6)
        nuevos, _ = optimizar_bytes(datos)

        ancho, alto = Image.open(io.BytesIO(nuevos)).size
        self.assertGreater(alto, ancho)

    def test_conserva_la_transparencia(self):
        datos = _imagen_bytes(3000, 3000, formato='PNG', modo='RGBA')
        nuevos, formato = optimizar_bytes(datos)

        self.assertEqual(formato, 'WEBP')
        self.assertIn(Image.open(io.BytesIO(nuevos)).mode, ('RGBA', 'LA', 'P'))

    def test_ignora_el_gif(self):
        # Puede estar animado y reencodarlo perdería el movimiento.
        self.assertIsNone(optimizar_bytes(_imagen_bytes(3000, 3000, formato='GIF', modo='P')))

    def test_no_revienta_con_basura(self):
        self.assertIsNone(optimizar_bytes(b'esto no es una imagen'))


class ArticleCoverOptimizationTests(AdminAPITestCase):
    def test_la_portada_se_achica_al_guardar(self):
        article = Article.objects.create(
            title='Con portada pesada',
            body='cuerpo',
            category=self.category,
            author=self.author,
            published_at=timezone.now(),
            cover_image=SimpleUploadedFile('foto.jpg', _imagen_bytes(4000, 3000), content_type='image/jpeg'),
        )

        article.refresh_from_db()
        with Image.open(article.cover_image) as img:
            self.assertEqual(max(img.size), 2400)

    def test_una_foto_vertical_de_celular_no_queda_como_apaisada(self):
        """El bug: un celular guarda el retrato apaisado más una marca EXIF de
        rotación. El navegador la respeta y muestra la foto vertical, pero el
        cálculo leía `img.size` crudo, la clasificaba 'landscape' y el sitio la
        recortaba a 21:9."""
        article = Article.objects.create(
            title='Retrato de celular',
            body='cuerpo',
            category=self.category,
            author=self.author,
            published_at=timezone.now(),
            cover_image=SimpleUploadedFile(
                'retrato.jpg', _imagen_bytes(4000, 3000, exif_orientacion=6), content_type='image/jpeg'
            ),
        )

        article.refresh_from_db()
        self.assertEqual(article.cover_image_orientation, 'portrait')

    def test_reguardar_no_vuelve_a_reencodar(self):
        article = Article.objects.create(
            title='Reguardado',
            body='cuerpo',
            category=self.category,
            author=self.author,
            published_at=timezone.now(),
            cover_image=SimpleUploadedFile('foto.jpg', _imagen_bytes(4000, 3000), content_type='image/jpeg'),
        )
        article.refresh_from_db()
        nombre, peso = article.cover_image.name, article.cover_image.size

        article.title = 'Reguardado otra vez'
        article.save()

        article.refresh_from_db()
        self.assertEqual(article.cover_image.name, nombre)
        self.assertEqual(article.cover_image.size, peso)


class InlineImageOptimizationTests(AdminAPITestCase):
    def test_la_imagen_del_cuerpo_se_achica(self):
        response = self.client.post(
            '/api/admin/media/',
            {'file': SimpleUploadedFile('grande.jpg', _imagen_bytes(2400, 1800), content_type='image/jpeg')},
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ruta = response.data['url'].split('/media/', 1)[1]
        with default_storage.open(f'{ruta}') as archivo:
            with Image.open(archivo) as img:
                self.assertEqual(max(img.size), 1600)


class OptimizarImagenGuardadaTests(AdminAPITestCase):
    """Las imágenes que ya estaban en disco antes de que existiera la
    optimización se procesan por el comando `optimizar_imagenes`, y ahí el
    campo ya tiene la ruta completa — no el nombre suelto que llega en una
    subida nueva."""

    def test_no_duplica_la_carpeta_al_renombrar(self):
        # El bug: `FieldFile.save()` vuelve a aplicar `upload_to`, así que
        # pasarle 'articles/foto.webp' daba 'articles/articles/foto.webp'.
        ruta = default_storage.save('articles/vieja.jpg', ContentFile(_imagen_bytes(4000, 3000)))
        article = Article.objects.create(
            title='Ya estaba en disco',
            body='cuerpo',
            category=self.category,
            author=self.author,
            published_at=timezone.now(),
        )
        Article.objects.filter(pk=article.pk).update(cover_image=ruta)
        article.refresh_from_db()

        self.assertTrue(optimizar_imagen(article.cover_image))

        self.assertEqual(article.cover_image.name, 'articles/vieja.webp')
        default_storage.delete(ruta)
        article.cover_image.delete(save=False)


class LibraryPieceModelTests(AdminAPITestCase):
    """La Biblioteca guarda obra ajena: lo que se prueba acá es que el orden sea
    alfabético (el índice público es A-Z, no una línea de tiempo) y que borrar
    gente no se lleve puesta la obra."""

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
        # Si el orden fuera por id, "Trilce" iría primero solo por haberse
        # cargado antes, y el índice A-Z saldría desordenado.
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
        # Al revés que con el narrador: una obra sin autor no es nada.
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

    def test_no_deja_el_original_en_disco(self):
        """El archivo que sube el editor se convierte a WebP y el original debe
        desaparecer. Mientras no se borraba, cada imagen ocupaba el doble: en
        producción se midieron 8 archivos huérfanos en las primeras semanas, y
        esa cuenta crece con cada publicación."""
        from pathlib import Path as _Path

        pieza = self._pieza(
            cover_image=SimpleUploadedFile('zzorig.jpg', _imagen_bytes(3000, 2000), content_type='image/jpeg')
        )
        pieza.refresh_from_db()
        self.assertTrue(pieza.cover_image.name.endswith('.webp'), pieza.cover_image.name)

        sobrantes = [p.name for p in _Path(MEDIA_DE_PRUEBA).rglob('zzorig*') if p.suffix != '.webp']
        self.assertEqual(sobrantes, [], f'quedó el original sin borrar: {sobrantes}')

    def test_al_publicar_se_sella_la_fecha(self):
        self.assertIsNotNone(self._pieza(status='published').published_at)

    def test_un_borrador_no_tiene_fecha(self):
        self.assertIsNone(self._pieza().published_at)


@override_settings(MEDIA_ROOT=MEDIA_DE_PRUEBA)
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
        self.assertEqual([p['title'] for p in self.client.get('/api/library/?genre=cuento').data], ['Paco Yunque'])

    def test_un_genero_que_no_existe_no_revienta(self):
        # El filtro llega de un parámetro de URL que cualquiera puede escribir
        # a mano: devuelve vacío, no un 400.
        self.assertEqual(list(self.client.get('/api/library/?genre=haiku').data), [])

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
        self.assertEqual(self.client.get('/api/library/sin-publicar/').status_code, status.HTTP_404_NOT_FOUND)


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
        self.assertEqual(len(self.client.get('/api/admin/library/').data), 1)

    def test_asigna_narrador(self):
        narrador = Author.objects.create(name='Bruno Odar')
        self.assertEqual(self._crear(narrator=narrador.pk).data['narrator']['name'], 'Bruno Odar')

    def test_sube_audio(self):
        # El campo tiene que estar en Meta.fields o DRF lo ignora en silencio
        # y la narración nunca llega al modelo.
        audio = SimpleUploadedFile('lectura.mp3', b'ID3\x04\x00' + b'\x00' * 200, content_type='audio/mpeg')
        pk = self._crear(audio=audio).data['id']
        self.assertTrue(LibraryPiece.objects.get(pk=pk).audio)

    def test_publica_con_patch(self):
        pk = self._crear().data['id']
        response = self.client.patch(f'/api/admin/library/{pk}/', {'status': 'published'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(LibraryPiece.objects.get(pk=pk).status, 'published')

    def test_no_borra_si_no_esta_en_papelera(self):
        # Mismo criterio que Article: el borrado definitivo siempre pasa antes
        # por la papelera, para que no esté a un clic del listado activo.
        pk = self._crear().data['id']
        self.assertEqual(self.client.delete(f'/api/admin/library/{pk}/').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(LibraryPiece.objects.filter(pk=pk).exists())

    def test_borra_si_esta_en_papelera(self):
        pk = self._crear(status='trashed').data['id']
        self.assertEqual(self.client.delete(f'/api/admin/library/{pk}/').status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LibraryPiece.objects.filter(pk=pk).exists())

    def test_sin_sesion_no_se_puede(self):
        self.client.credentials()
        self.assertIn(self.client.get('/api/admin/library/').status_code, (401, 403))

    def test_borrar_un_autor_con_piezas_da_400_con_mensaje(self):
        # AdminAuthorDeleteView ya traduce ProtectedError a 400. Al sumar una FK
        # PROTECT nueva desde LibraryPiece ese camino tiene que seguir andando:
        # si no, borrar un autor tira un 500.
        self._crear()
        response = self.client.delete(f'/api/admin/authors/{self.author.pk}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Biblioteca', response.data['detail'])


class NombreDeArchivoOptimizadoTests(AdminAPITestCase):
    """El nombre nuevo se arma a partir del que manda el cliente, que puede ser
    cualquier cosa: emojis, kanji, solo signos. Django le saca todo lo que no
    sea ASCII al guardar, así que un nombre mal armado puede colapsar a solo la
    extensión."""

    def _subir(self, nombre_archivo):
        pieza = LibraryPiece.objects.create(
            title='Con portada', author=self.author, genre='poema',
            cover_image=SimpleUploadedFile(nombre_archivo, _imagen_bytes(3000, 3000), content_type='image/jpeg'),
        )
        pieza.refresh_from_db()
        return pieza.cover_image.name.split('/')[-1]

    def test_un_nombre_de_solo_simbolos_no_deja_el_archivo_sin_nombre(self):
        # Este es el caso real: una foto llamada "☆.jpeg" terminaba guardada
        # como "library/.webp" — sin nombre, y chocando con cualquier otra
        # igual de anónima.
        nombre = self._subir('☆.jpeg')
        self.assertNotEqual(nombre, '.webp')
        self.assertTrue(nombre.endswith('.webp'))
        self.assertGreater(len(nombre), len('.webp'))

    def test_conserva_un_nombre_normal(self):
        # startswith y no igualdad: si ya existe un retrato.webp en disco,
        # Django le agrega un sufijo aleatorio. Eso es correcto y no es lo que
        # se está probando acá.
        nombre = self._subir('retrato.jpg')
        self.assertTrue(nombre.startswith('retrato'), nombre)
        self.assertTrue(nombre.endswith('.webp'), nombre)

    def test_las_tildes_y_la_enhe_no_rompen_el_nombre(self):
        nombre = self._subir('ñandú.jpg')
        self.assertTrue(nombre.endswith('.webp'))
        self.assertGreater(len(nombre), len('.webp'))

    def test_dos_archivos_anonimos_no_se_pisan(self):
        self.assertNotEqual(self._subir('☆.jpeg'), self._subir('★.jpeg'))


class PortadaPanoramicaTests(AdminAPITestCase):
    """Las portadas de las entrevistas son banners de 2400x630 con el nombre
    escrito grande. Tratadas como una foto apaisada cualquiera, la caja 3:2 de
    la tarjeta les cortaba el 61% del ancho y el nombre quedaba ilegible."""

    def _con_portada(self, w, h):
        art = Article.objects.create(
            title=f'Portada {w}x{h}', body='x', category=self.category, author=self.author,
            published_at=timezone.now(),
            cover_image=SimpleUploadedFile(f'{w}x{h}.jpg', _imagen_bytes(w, h), content_type='image/jpeg'),
        )
        art.refresh_from_db()
        return art

    def test_un_banner_se_marca_como_panoramico(self):
        self.assertEqual(self._con_portada(2400, 630).cover_image_orientation, 'panoramic')

    def test_una_foto_apaisada_normal_sigue_siendo_horizontal(self):
        # 3:2 y 16:9 son fotos, no banners: toleran el recorte.
        self.assertEqual(self._con_portada(1800, 1200).cover_image_orientation, 'landscape')
        self.assertEqual(self._con_portada(1920, 1080).cover_image_orientation, 'landscape')

    def test_el_limite_esta_en_2_2(self):
        self.assertEqual(self._con_portada(2100, 1000).cover_image_orientation, 'landscape')   # 2.10
        self.assertEqual(self._con_portada(2300, 1000).cover_image_orientation, 'panoramic')   # 2.30

    def test_guarda_las_medidas_reales(self):
        # Se guardan DESPUÉS de optimizar, así que son las del archivo que se
        # sirve, no las del original: el frontend arma la caja con estas.
        art = self._con_portada(2400, 630)
        self.assertEqual((art.cover_image_width, art.cover_image_height), (2400, 630))

    def test_las_medidas_son_las_del_archivo_ya_achicado(self):
        art = self._con_portada(4000, 1000)
        self.assertEqual(art.cover_image_width, 2400)
        with Image.open(art.cover_image) as img:
            self.assertEqual(img.size, (art.cover_image_width, art.cover_image_height))

    def test_una_vertical_no_se_confunde(self):
        self.assertEqual(self._con_portada(1000, 2400).cover_image_orientation, 'portrait')


class RecalculoDePortadasTests(AdminAPITestCase):
    """La migración 0009 arregla las portadas que ya estaban cargadas.

    Sin ella, desplegar la detección de banners no cambia nada: la orientación
    se calcula en `save()`, así que los artículos viejos se quedan como están y
    las entrevistas se siguen viendo recortadas. Pasó de verdad en producción.
    """

    def _pre_migracion(self, ancho, alto):
        """Un artículo como quedaban antes: con portada, pero con la
        orientación vieja y sin medidas."""
        art = Article.objects.create(
            title=f'Vieja {ancho}x{alto}', body='x', category=self.category, author=self.author,
            published_at=timezone.now(),
            cover_image=SimpleUploadedFile(f'v{ancho}.jpg', _imagen_bytes(ancho, alto), content_type='image/jpeg'),
        )
        Article.objects.filter(pk=art.pk).update(
            cover_image_orientation='landscape', cover_image_width=None, cover_image_height=None
        )
        return art.pk

    def _correr_migracion(self):
        import importlib

        from django.apps import apps

        modulo = importlib.import_module('content.migrations.0009_recalcular_portadas')
        modulo.recalcular(apps, None)

    def test_un_banner_viejo_pasa_a_panoramico(self):
        pk = self._pre_migracion(2400, 630)
        self._correr_migracion()
        art = Article.objects.get(pk=pk)
        self.assertEqual(art.cover_image_orientation, 'panoramic')
        self.assertEqual((art.cover_image_width, art.cover_image_height), (2400, 630))

    def test_una_foto_vieja_queda_horizontal(self):
        pk = self._pre_migracion(1800, 1200)
        self._correr_migracion()
        self.assertEqual(Article.objects.get(pk=pk).cover_image_orientation, 'landscape')

    def test_una_vertical_mal_clasificada_se_corrige(self):
        pk = self._pre_migracion(1000, 1500)
        self._correr_migracion()
        self.assertEqual(Article.objects.get(pk=pk).cover_image_orientation, 'portrait')

    def test_una_portada_que_falta_en_disco_no_voltea_la_migracion(self):
        pk = self._pre_migracion(1800, 1200)
        art = Article.objects.get(pk=pk)
        art.cover_image.storage.delete(art.cover_image.name)
        self._correr_migracion()  # no debe levantar
        self.assertEqual(Article.objects.get(pk=pk).cover_image_orientation, 'landscape')


class GenerosDeBibliotecaTests(AdminAPITestCase):
    def test_se_pueden_guardar_los_ocho_generos(self):
        esperados = ['cuento', 'microcuento', 'novela', 'poema', 'cronica', 'ensayo', 'discurso', 'otros']
        self.assertEqual([v for v, _ in LibraryPiece.GENRE_CHOICES], esperados)
        for genero in esperados:
            pieza = LibraryPiece.objects.create(title=f'Pieza {genero}', author=self.author, genre=genero)
            pieza.refresh_from_db()
            self.assertEqual(pieza.genre, genero)

    def test_todos_entran_en_el_campo(self):
        largo = LibraryPiece._meta.get_field('genre').max_length
        for valor, _ in LibraryPiece.GENRE_CHOICES:
            self.assertLessEqual(len(valor), largo, valor)

    def test_el_filtro_publico_anda_con_los_nuevos(self):
        LibraryPiece.objects.create(title='Una novela', author=self.author, genre='novela', status='published')
        LibraryPiece.objects.create(title='Un discurso', author=self.author, genre='discurso', status='published')
        self.assertEqual([p['title'] for p in self.client.get('/api/library/?genre=novela').data], ['Una novela'])
        self.assertEqual([p['title'] for p in self.client.get('/api/library/?genre=discurso').data], ['Un discurso'])


class NarradosPublicAPITests(APITestCase):
    """`/api/narrated/` — la lista única de todo lo que tiene voz."""

    def setUp(self):
        # Igual que en las demás: la caché del limitador de tasa es de proceso y
        # sobrevive de un test al siguiente, así que sin esto la suite falla
        # según el orden y la cantidad de pruebas.
        cache.clear()
        self.categoria = Category.objects.create(slug='critica-literaria', label='Crítica Literaria')
        self.autor = Author.objects.create(name='César Vallejo')
        self.narradora = Author.objects.create(name='Delfina Paredes')
        ahora = timezone.now()

        def crear_articulo(titulo, dias, **extra):
            datos = {
                'title': titulo,
                'excerpt': 'resumen',
                'category': self.categoria,
                'author': self.autor,
                'published_at': ahora - timezone.timedelta(days=dias),
                'status': 'published',
                'narration_audio': 'narration/lectura.mp3',
            }
            datos.update(extra)
            return Article.objects.create(**datos)

        def crear_pieza(titulo, dias, **extra):
            datos = {
                'title': titulo,
                'author': self.autor,
                'narrator': self.narradora,
                'genre': 'poema',
                'body': 'verso',
                'status': 'published',
                'published_at': ahora - timezone.timedelta(days=dias),
                'audio': 'library-audio/lectura.mp3',
            }
            datos.update(extra)
            return LibraryPiece.objects.create(**datos)

        # Intercalados a propósito, para que un orden correcto solo pueda salir
        # de mezclar los dos modelos y no de concatenarlos.
        crear_articulo('Artículo reciente', 1)
        crear_pieza('Pieza del medio', 2)
        crear_articulo('Artículo viejo', 3)
        crear_pieza('Pieza vieja', 4)
        # Los que NO tienen que salir.
        crear_articulo('Artículo borrador', 1, status='draft')
        crear_articulo('Artículo sin audio', 1, narration_audio='')
        crear_pieza('Pieza borrador', 1, status='draft')
        crear_pieza('Pieza sin audio', 1, audio='')

    def test_mezcla_los_dos_tipos_ordenados_por_fecha(self):
        response = self.client.get('/api/narrated/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item['title'] for item in response.data['items']],
            ['Artículo reciente', 'Pieza del medio', 'Artículo viejo', 'Pieza vieja'],
        )
        self.assertEqual(response.data['total'], 4)

    def test_devuelve_la_forma_comun_de_un_articulo(self):
        item = self.client.get('/api/narrated/').data['items'][0]
        self.assertEqual(item['kind'], 'article')
        self.assertEqual(item['url'], '/articulo/articulo-reciente/')
        self.assertEqual(item['label'], 'Crítica Literaria')
        self.assertEqual(item['author']['name'], 'César Vallejo')
        self.assertIsNone(item['narrator'])
        self.assertIn('lectura.mp3', item['audioUrl'])
        self.assertIsNone(item['coverImageUrl'])

    def test_devuelve_la_forma_comun_de_una_pieza(self):
        item = self.client.get('/api/narrated/').data['items'][1]
        self.assertEqual(item['kind'], 'library')
        self.assertEqual(item['url'], '/biblioteca/pieza-del-medio/')
        self.assertEqual(item['label'], 'Poema')
        self.assertEqual(item['narrator']['name'], 'Delfina Paredes')
        self.assertEqual(item['excerpt'], 'verso')

    def test_la_url_siempre_termina_en_barra(self):
        # trailingSlash: 'always' en el frontend: sin la barra final el enlace da
        # 404 en vez de redirigir.
        for item in self.client.get('/api/narrated/').data['items']:
            self.assertTrue(item['url'].endswith('/'), item['url'])

    def test_filtra_por_tipo_articulo(self):
        response = self.client.get('/api/narrated/?type=article')
        self.assertEqual([i['title'] for i in response.data['items']], ['Artículo reciente', 'Artículo viejo'])
        self.assertEqual(response.data['total'], 2)

    def test_filtra_por_tipo_biblioteca(self):
        response = self.client.get('/api/narrated/?type=library')
        self.assertEqual([i['title'] for i in response.data['items']], ['Pieza del medio', 'Pieza vieja'])
        self.assertEqual(response.data['total'], 2)

    def test_un_tipo_invalido_da_400(self):
        response = self.client.get('/api/narrated/?type=podcast')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('type', response.data)

    def test_no_aparecen_borradores_ni_contenido_sin_audio(self):
        titulos = {i['title'] for i in self.client.get('/api/narrated/').data['items']}
        self.assertEqual(
            titulos & {'Artículo borrador', 'Artículo sin audio', 'Pieza borrador', 'Pieza sin audio'},
            set(),
        )

    def test_pagina_sin_repetir_ni_perder_filas(self):
        primera = self.client.get('/api/narrated/?pageSize=2&page=1').data
        segunda = self.client.get('/api/narrated/?pageSize=2&page=2').data
        self.assertEqual([i['title'] for i in primera['items']], ['Artículo reciente', 'Pieza del medio'])
        self.assertEqual([i['title'] for i in segunda['items']], ['Artículo viejo', 'Pieza vieja'])
        # El total es el de la colección completa, no el de la página.
        self.assertEqual(primera['total'], 4)
        self.assertEqual(segunda['total'], 4)

    def test_una_pagina_que_no_existe_da_404(self):
        self.assertEqual(
            self.client.get('/api/narrated/?pageSize=2&page=9').status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_la_paginacion_respeta_el_filtro_por_tipo(self):
        response = self.client.get('/api/narrated/?type=library&pageSize=1&page=2').data
        self.assertEqual([i['title'] for i in response['items']], ['Pieza vieja'])
        self.assertEqual(response['total'], 2)


class RegionImagenTests(AdminAPITestCase):
    """La imagen referente de cada región del Mapa Regional.

    Hereda de AdminAPITestCase por el MEDIA_ROOT temporal y el cache.clear()
    del limitador de tasa: estas pruebas suben archivos de verdad y sin eso
    ensuciarían el media/ del proyecto.
    """

    def _subir(self, region=None, nombre='plaza.jpg', ancho=1600, alto=1200):
        destino = region or self.region
        return self.client.patch(
            f'/api/admin/regions/{destino.id}/',
            {'image': SimpleUploadedFile(nombre, _imagen_bytes(ancho, alto), content_type='image/jpeg')},
            format='multipart',
        )

    def test_la_imagen_se_optimiza_a_webp_y_se_achica(self):
        respuesta = self._subir()
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)

        self.region.refresh_from_db()
        self.assertTrue(self.region.image.name.endswith('.webp'), self.region.image.name)
        with Image.open(self.region.image) as img:
            self.assertEqual(max(img.size), Region.MAX_SIDE_MINIATURA)

    def test_el_nombre_no_anida_la_carpeta(self):
        # El bug conocido: `FieldFile.save()` vuelve a aplicar `upload_to`, así
        # que pasarle la ruta completa daba 'regions/regions/plaza.webp'.
        self._subir()
        self.region.refresh_from_db()
        self.assertTrue(self.region.image.name.startswith('regions/'), self.region.image.name)
        self.assertNotIn('regions/regions/', self.region.image.name)

    def test_reguardar_no_vuelve_a_reencodar(self):
        self._subir()
        self.region.refresh_from_db()
        nombre, peso = self.region.image.name, self.region.image.size

        self.region.save()

        self.region.refresh_from_db()
        self.assertEqual(self.region.image.name, nombre)
        self.assertEqual(self.region.image.size, peso)

    def test_se_puede_quitar_la_imagen(self):
        self._subir()
        self.region.refresh_from_db()
        ruta_anterior = self.region.image.name

        respuesta = self.client.patch(f'/api/admin/regions/{self.region.id}/', {'image': None}, format='json')

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIsNone(respuesta.data['imageUrl'])
        self.region.refresh_from_db()
        self.assertFalse(self.region.image)
        # El archivo no queda huérfano en disco.
        self.assertFalse(default_storage.exists(ruta_anterior))

    def test_sin_autenticacion_no_se_puede_modificar(self):
        self.client.credentials()
        respuesta = self._subir()
        self.assertEqual(respuesta.status_code, status.HTTP_401_UNAUTHORIZED)
        self.region.refresh_from_db()
        self.assertFalse(self.region.image)

    def test_image_url_es_null_sin_imagen(self):
        respuesta = self.client.get('/api/regions/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        propia = next(r for r in respuesta.data if r['code'] == self.region.code)
        self.assertIsNone(propia['imageUrl'])

    def test_image_url_es_absoluta_cuando_hay_imagen(self):
        self._subir()
        respuesta = self.client.get('/api/regions/')
        propia = next(r for r in respuesta.data if r['code'] == self.region.code)
        self.assertTrue(propia['imageUrl'].startswith('http://'), propia['imageUrl'])
        self.assertIn('/media/regions/', propia['imageUrl'])


class LetraCapitalTests(AdminAPITestCase):
    """El interruptor de letra capital (`drop_cap`) de Article y LibraryPiece.

    Es una propiedad de la pieza, no un formato de párrafo: lo único que hay
    que garantizar es que nazca apagada y que viaje en las dos direcciones —
    que el panel la pueda encender y que la lectura pública la devuelva, que es
    de donde el frontend decide si dibuja la capital.
    """

    def _crear_articulo(self, **extra):
        datos = {
            'title': 'Con capital',
            'excerpt': 'Resumen',
            'body': '«Nadie sabía nada.',
            'category': self.category.slug,
            'author': self.author.id,
            'status': 'published',
        }
        datos.update(extra)
        return self.client.post('/api/admin/articles/', datos, format='multipart')

    def _crear_pieza(self, **extra):
        datos = {'title': 'Masa', 'author': self.author.pk, 'genre': 'poema', 'body': 'verso', 'status': 'published'}
        datos.update(extra)
        return self.client.post('/api/admin/library/', datos, format='multipart')

    # ── Por defecto está apagada ──

    def test_un_articulo_nace_sin_capital(self):
        article = Article.objects.create(
            title='Sin capital', excerpt='x', body='x',
            category=self.category, author=self.author, published_at=timezone.now(),
        )
        self.assertFalse(article.drop_cap)

    def test_una_pieza_nace_sin_capital(self):
        self.assertFalse(LibraryPiece.objects.create(title='Masa', author=self.author, genre='poema').drop_cap)

    def test_el_articulo_creado_sin_mandar_el_campo_queda_apagado(self):
        self.assertIs(self._crear_articulo().data['dropCap'], False)

    def test_la_pieza_creada_sin_mandar_el_campo_queda_apagada(self):
        self.assertIs(self._crear_pieza().data['dropCap'], False)

    # ── Escritura desde el panel ──

    def test_el_panel_enciende_la_capital_de_un_articulo(self):
        respuesta = self._crear_articulo(dropCap=True)
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED)
        self.assertIs(respuesta.data['dropCap'], True)
        self.assertTrue(Article.objects.get(pk=respuesta.data['id']).drop_cap)

    def test_el_panel_apaga_la_capital_de_un_articulo(self):
        creado = self._crear_articulo(dropCap=True)
        respuesta = self.client.patch(
            f'/api/admin/articles/{creado.data["id"]}/', {'dropCap': False}, format='multipart'
        )
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIs(respuesta.data['dropCap'], False)
        self.assertFalse(Article.objects.get(pk=creado.data['id']).drop_cap)

    def test_el_panel_enciende_la_capital_de_una_pieza(self):
        respuesta = self._crear_pieza(dropCap=True)
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED)
        self.assertIs(respuesta.data['dropCap'], True)
        self.assertTrue(LibraryPiece.objects.get(pk=respuesta.data['id']).drop_cap)

    def test_el_panel_apaga_la_capital_de_una_pieza(self):
        creada = self._crear_pieza(dropCap=True)
        respuesta = self.client.patch(
            f'/api/admin/library/{creada.data["id"]}/', {'dropCap': False}, format='multipart'
        )
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIs(respuesta.data['dropCap'], False)
        self.assertFalse(LibraryPiece.objects.get(pk=creada.data['id']).drop_cap)

    # ── Lectura pública ──

    def test_el_detalle_publico_del_articulo_trae_la_capital(self):
        slug = self._crear_articulo(dropCap=True).data['slug']
        self.client.credentials()
        respuesta = self.client.get(f'/api/articles/{slug}/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIs(respuesta.data['dropCap'], True)

    def test_el_listado_publico_de_articulos_trae_la_capital(self):
        self._crear_articulo(dropCap=True)
        self.client.credentials()
        respuesta = self.client.get('/api/articles/')
        self.assertIs(respuesta.data['items'][0]['dropCap'], True)

    def test_el_detalle_publico_de_la_pieza_trae_la_capital(self):
        slug = self._crear_pieza(dropCap=True).data['slug']
        self.client.credentials()
        respuesta = self.client.get(f'/api/library/{slug}/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIs(respuesta.data['dropCap'], True)

    def test_el_publico_no_puede_escribir_la_capital(self):
        # El serializer público la declara read_only: un PATCH sin sesión ni
        # siquiera llega, pero lo que se fija acá es que el campo no sea una
        # puerta de escritura abierta en el detalle.
        slug = self._crear_articulo().data['slug']
        self.client.credentials()
        respuesta = self.client.patch(f'/api/articles/{slug}/', {'dropCap': True}, format='json')
        self.assertIn(respuesta.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED))
        self.assertFalse(Article.objects.get(slug=slug).drop_cap)


class RegionInternacionalTests(AdminAPITestCase):
    """La región "Internacional": autores que escriben desde fuera del Perú.

    El cliente pidió una pestaña "Internacional" y una opción "Internacional"
    en el desplegable de región. Se resolvió con lo segundo: es una región más,
    así que funciona en todas las secciones y no agrega un noveno ítem al menú.

    La crea la migración 0013, no el panel — de ahí que estas pruebas no la
    creen: si falta, es que la migración no corrió y eso es justo lo que hay
    que detectar.
    """

    def _internacional(self):
        return Region.objects.get(code=Region.CODE_INTERNACIONAL)

    def _correr_migracion(self):
        import importlib

        from django.apps import apps

        modulo = importlib.import_module('content.migrations.0013_region_internacional')
        modulo.crear_internacional(apps, None)

    def test_la_migracion_la_creo(self):
        region = self._internacional()
        self.assertEqual(region.name, 'Internacional')
        self.assertTrue(region.es_internacional)

    def test_el_codigo_no_puede_chocar_con_uno_del_INEI(self):
        # Los códigos del INEI son numéricos de dos o tres cifras. Mientras el
        # de Internacional sea alfabético, no hay colisión posible.
        self.assertFalse(Region.CODE_INTERNACIONAL.isdigit())

    def test_correr_la_migracion_de_nuevo_no_duplica(self):
        self._correr_migracion()
        self._correr_migracion()
        self.assertEqual(Region.objects.filter(code=Region.CODE_INTERNACIONAL).count(), 1)

    def test_correr_la_migracion_de_nuevo_no_pisa_el_nombre(self):
        # get_or_create con defaults: si alguien ajustó el nombre desde la
        # base, una segunda corrida lo respeta.
        Region.objects.filter(code=Region.CODE_INTERNACIONAL).update(name='Internacional (editado)')
        self._correr_migracion()
        self.assertEqual(self._internacional().name, 'Internacional (editado)')

    def test_la_api_publica_de_regiones_la_devuelve_marcada(self):
        self.client.credentials()
        respuesta = self.client.get('/api/regions/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        internacional = next(r for r in respuesta.data if r['code'] == Region.CODE_INTERNACIONAL)
        self.assertEqual(internacional['name'], 'Internacional')
        self.assertIs(internacional['isInternational'], True)

    def test_las_regiones_del_peru_no_vienen_marcadas(self):
        # La bandera es lo único que usa el frontend para sacarla de la grilla
        # del Mapa Regional, así que un falso positivo escondería una región
        # peruana del mapa.
        self.client.credentials()
        respuesta = self.client.get('/api/regions/')
        propia = next(r for r in respuesta.data if r['code'] == self.region.code)
        self.assertIs(propia['isInternational'], False)

    def test_su_pagina_responde_y_lista_sus_piezas(self):
        Article.objects.create(
            title='Carta desde Berlín',
            slug='carta-desde-berlin',
            excerpt='x',
            body='x',
            category=self.category,
            author=self.author,
            region=self._internacional(),
            published_at=timezone.now(),
            status='published',
        )
        self.client.credentials()

        detalle = self.client.get(f'/api/regions/{Region.CODE_INTERNACIONAL}/')
        self.assertEqual(detalle.status_code, status.HTTP_200_OK)
        self.assertEqual(detalle.data['articleCount'], 1)

        listado = self.client.get(f'/api/articles/?region={Region.CODE_INTERNACIONAL}')
        self.assertEqual(listado.status_code, status.HTTP_200_OK)
        slugs = [a['slug'] for a in listado.data['items']]
        self.assertIn('carta-desde-berlin', slugs)

    def test_lista_sus_autores(self):
        Author.objects.create(name='Autor de Berlín', region=self._internacional())
        self.client.credentials()
        respuesta = self.client.get(f'/api/regions/{Region.CODE_INTERNACIONAL}/authors/')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertEqual([a['name'] for a in respuesta.data], ['Autor de Berlín'])

    def test_no_se_puede_borrar_desde_el_panel(self):
        respuesta = self.client.delete(f'/api/admin/regions/{self._internacional().id}/')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Internacional', respuesta.data['detail'])
        self.assertTrue(Region.objects.filter(code=Region.CODE_INTERNACIONAL).exists())

    def test_borrarla_no_deja_sin_region_a_sus_publicaciones(self):
        # El daño concreto que evita la protección: Article.region es SET_NULL,
        # así que un borrado exitoso vaciaría la región de cada pieza en
        # silencio.
        articulo = Article.objects.create(
            title='Reseña desde Madrid',
            slug='resena-desde-madrid',
            excerpt='x',
            body='x',
            category=self.category,
            author=self.author,
            region=self._internacional(),
            published_at=timezone.now(),
            status='published',
        )
        self.client.delete(f'/api/admin/regions/{self._internacional().id}/')
        articulo.refresh_from_db()
        self.assertIsNotNone(articulo.region)

    def test_las_demas_regiones_se_siguen_borrando(self):
        respuesta = self.client.delete(f'/api/admin/regions/{self.region.id}/')
        self.assertEqual(respuesta.status_code, status.HTTP_204_NO_CONTENT)

    def test_se_le_puede_cargar_imagen_como_a_cualquier_region(self):
        respuesta = self.client.patch(
            f'/api/admin/regions/{self._internacional().id}/',
            {'image': SimpleUploadedFile('mundo.jpg', _imagen_bytes(1600, 1200), content_type='image/jpeg')},
            format='multipart',
        )
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(respuesta.data['imageUrl'])


class GeneroDelLibroResenadoTests(AdminAPITestCase):
    """El género del LIBRO RESEÑADO en una pieza de Crítica.

    No es el género de la reseña: la pieza es un texto crítico y lo que se
    clasifica es la obra de la que habla. Por eso tiene lista propia y no la de
    la Biblioteca (ver el comentario de Article.REVIEWED_GENRE_CHOICES)."""

    def _resena(self, **extra):
        datos = {
            'title': extra.pop('title', 'Reseña de prueba'),
            'excerpt': 'x',
            'body': 'x',
            'category': self.category.slug,
            'author': self.author.id,
            'status': 'published',
        }
        datos.update(extra)
        return self.client.post('/api/admin/articles/', datos, format='multipart')

    def test_son_los_seis_que_pidio_el_cliente(self):
        self.assertEqual(
            Article.REVIEWED_GENRE_CHOICES,
            [
                ('cuento', 'Cuento'),
                ('novela', 'Novela'),
                ('poesia', 'Poesía'),
                ('ensayo', 'Ensayo'),
                ('cronica', 'Crónica'),
                ('otros', 'Otros textos'),
            ],
        )

    def test_todos_entran_en_el_campo(self):
        largo = Article._meta.get_field('reviewed_genre').max_length
        for valor, _ in Article.REVIEWED_GENRE_CHOICES:
            self.assertLessEqual(len(valor), largo, valor)

    def test_se_guarda_desde_el_panel_y_vuelve_en_camel_case(self):
        respuesta = self._resena(reviewedGenre='novela')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED)
        self.assertEqual(respuesta.data['reviewedGenre'], 'novela')
        self.assertEqual(Article.objects.get(pk=respuesta.data['id']).reviewed_genre, 'novela')

    def test_viaja_al_sitio_publico(self):
        slug = self._resena(reviewedGenre='poesia').data['slug']
        self.client.credentials()
        self.assertEqual(self.client.get(f'/api/articles/{slug}/').data['reviewedGenre'], 'poesia')
        listado = self.client.get('/api/articles/').data['items']
        self.assertEqual([p['reviewedGenre'] for p in listado], ['poesia'])

    def test_se_puede_volver_a_dejar_sin_genero(self):
        # El camino de vuelta: el editor eligió mal y pone "Sin especificar".
        pk = self._resena(reviewedGenre='cronica').data['id']
        respuesta = self.client.patch(f'/api/admin/articles/{pk}/', {'reviewedGenre': ''}, format='multipart')
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertEqual(Article.objects.get(pk=pk).reviewed_genre, '')

    def test_un_genero_inventado_desde_el_panel_da_400(self):
        respuesta = self._resena(reviewedGenre='haiku')
        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('reviewedGenre', respuesta.data)

    def test_el_filtro_publico_separa_por_genero(self):
        self._resena(title='Un libro de cuentos', reviewedGenre='cuento')
        self._resena(title='Una novela larga', reviewedGenre='novela')
        self.client.credentials()
        listado = self.client.get('/api/articles/?reviewedGenre=cuento').data['items']
        self.assertEqual([p['title'] for p in listado], ['Un libro de cuentos'])

    def test_un_genero_invalido_en_el_filtro_da_400(self):
        # Mismo criterio que ?limit= con basura: 400 y no un 500 ni una lista
        # vacía que se confunda con "no hay piezas de ese género".
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/articles/?reviewedGenre=haiku').status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_una_pieza_sin_genero_sigue_apareciendo_en_el_listado(self):
        # Lo que NO puede pasar: las reseñas que ya están cargadas no tienen
        # género y tienen que seguir viéndose en Crítica.
        self._resena(title='Reseña vieja sin género')
        self.client.credentials()
        listado = self.client.get('/api/articles/?category=articulos').data['items']
        self.assertEqual([p['title'] for p in listado], ['Reseña vieja sin género'])
        self.assertEqual(listado[0]['reviewedGenre'], '')

    def test_una_pieza_sin_genero_no_sale_al_filtrar(self):
        self._resena(title='Sin género')
        self._resena(title='Con género', reviewedGenre='ensayo')
        self.client.credentials()
        listado = self.client.get('/api/articles/?reviewedGenre=ensayo').data['items']
        self.assertEqual([p['title'] for p in listado], ['Con género'])

    def test_una_entrevista_no_se_queda_con_el_genero_colgado(self):
        # El campo es de Crítica: si la pieza se mueve a otra sección, el
        # género del libro reseñado deja de tener sentido y se limpia al
        # guardar en vez de rechazar el guardado entero.
        entrevistas = Category.objects.create(slug='entrevistas', label='Entrevistas')
        respuesta = self._resena(title='Charla con alguien', category=entrevistas.slug, reviewedGenre='novela')
        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Article.objects.get(pk=respuesta.data['id']).reviewed_genre, '')

    def test_mover_una_resena_a_otra_categoria_le_saca_el_genero(self):
        entrevistas = Category.objects.create(slug='entrevistas', label='Entrevistas')
        pk = self._resena(reviewedGenre='cuento').data['id']
        self.client.patch(f'/api/admin/articles/{pk}/', {'category': entrevistas.slug}, format='multipart')
        self.assertEqual(Article.objects.get(pk=pk).reviewed_genre, '')


@override_settings(MEDIA_ROOT=MEDIA_DE_PRUEBA)
class ArchivosSinDuenoTests(TestCase):
    """Django no borra del disco el archivo de un FileField, ni al eliminar el
    registro ni al reemplazarlo. En producción se midieron 8 archivos sin dueño
    en las primeras semanas; como el 96 % del disco es audio de narraciones de
    decenas de megas, cada reemplazo que no se limpia se paga en almacenamiento."""

    def setUp(self):
        self.region = Region.objects.create(name='Arequipa', code='040')
        self.author = Author.objects.create(name='César Vallejo', region=self.region)
        self.categoria, _ = Category.objects.get_or_create(
            slug='articulos', defaults={'label': 'Crítica'}
        )

    def _subida(self, nombre):
        return SimpleUploadedFile(nombre, _imagen_bytes(900, 600), content_type='image/jpeg')

    def _existe(self, campo):
        return campo.storage.exists(campo.name)

    def test_al_borrar_la_pieza_se_borra_su_portada(self):
        pieza = LibraryPiece.objects.create(
            title='Masa', author=self.author, genre='poema', cover_image=self._subida('zzdel.jpg')
        )
        ruta, almacen = pieza.cover_image.name, pieza.cover_image.storage
        self.assertTrue(almacen.exists(ruta))

        with self.captureOnCommitCallbacks(execute=True):
            pieza.delete()
        self.assertFalse(almacen.exists(ruta), 'la portada quedó en disco sin dueño')

    def test_al_reemplazar_la_portada_se_borra_la_anterior(self):
        pieza = LibraryPiece.objects.create(
            title='Masa', author=self.author, genre='poema', cover_image=self._subida('zzvieja.jpg')
        )
        anterior, almacen = pieza.cover_image.name, pieza.cover_image.storage

        pieza.cover_image = self._subida('zznueva.jpg')
        with self.captureOnCommitCallbacks(execute=True):
            pieza.save()

        self.assertFalse(almacen.exists(anterior), 'la portada anterior quedó en disco')
        self.assertTrue(almacen.exists(pieza.cover_image.name), 'se borró la portada nueva')

    def test_guardar_sin_tocar_la_portada_no_la_borra(self):
        """El caso que rompería todo: editar el título de una pieza NO puede
        llevarse puesta su imagen."""
        pieza = LibraryPiece.objects.create(
            title='Masa', author=self.author, genre='poema', cover_image=self._subida('zzintacta.jpg')
        )
        pieza.title = 'Masa (revisado)'
        with self.captureOnCommitCallbacks(execute=True):
            pieza.save()

        pieza.refresh_from_db()
        self.assertTrue(self._existe(pieza.cover_image), 'se borró la portada de una pieza que no la cambió')

    def test_al_borrar_el_articulo_se_borra_su_narracion(self):
        articulo = Article.objects.create(
            title='ZZ con voz', excerpt='x', body='x',
            category=self.categoria,
            author=self.author, status='published', published_at=timezone.now(),
            narration_audio=SimpleUploadedFile('zzvoz.mp3', b'audio falso', content_type='audio/mpeg'),
        )
        ruta, almacen = articulo.narration_audio.name, articulo.narration_audio.storage
        with self.captureOnCommitCallbacks(execute=True):
            articulo.delete()
        self.assertFalse(almacen.exists(ruta), 'el audio quedó en disco sin dueño')

    def test_todos_los_modelos_con_archivos_estan_cubiertos(self):
        """Si mañana alguien agrega un FileField y no lo suma al registro, sus
        archivos empiezan a acumularse en silencio. Esta prueba lo impide."""
        from django.db.models import FileField

        from content import archivos, models as modelos

        faltantes = []
        for modelo in apps.get_app_config('content').get_models():
            campos = {c.name for c in modelo._meta.get_fields() if isinstance(c, FileField)}
            if not campos:
                continue
            cubiertos = set(archivos.CAMPOS_DE_ARCHIVO.get(modelo, ()))
            if campos - cubiertos:
                faltantes.append(f'{modelo.__name__}: {sorted(campos - cubiertos)}')

        self.assertEqual(faltantes, [], f'campos de archivo sin limpieza: {faltantes}')
