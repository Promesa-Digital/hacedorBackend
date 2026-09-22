import io
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
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


class AdminAPITestCase(APITestCase):
    """Base con un usuario admin autenticado vía Bearer y taxonomía mínima."""

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

    def test_al_publicar_se_sella_la_fecha(self):
        self.assertIsNotNone(self._pieza(status='published').published_at)

    def test_un_borrador_no_tiene_fecha(self):
        self.assertIsNone(self._pieza().published_at)


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
