import io
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from .admin_views import AdminInlineImageUploadView
from .embeds import normalize_spotify_embed_url, normalize_youtube_embed_url
from .models import Article, Author, Category, Event, NewsletterSubscriber, Region, Tag


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
