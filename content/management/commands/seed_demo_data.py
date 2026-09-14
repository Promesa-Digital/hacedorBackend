"""
Carga el mismo contenido de demostración que hoy vive hardcodeado en
../frontend/src/lib/api.ts, para que frontend y backend
muestren exactamente lo mismo mientras se hace la integración.

Idempotente: se puede correr varias veces sin duplicar (get_or_create por
slug/código). No toca datos editados a mano después de la primera carga.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from content.models import Article, Author, Category, Region, Tag, Volume

DEMO_USER = {'username': 'demo', 'email': 'demo@elhacedor.pe', 'password': 'demo1234'}

NOW = datetime(2026, 7, 27, tzinfo=dt_timezone.utc)


def days_ago(n):
    return NOW - timedelta(days=n)


CATEGORIES = [
    {'slug': 'articulos', 'label': 'Artículos', 'color_variant': 'primary'},
    {'slug': 'entrevistas', 'label': 'Entrevistas', 'color_variant': 'secondary'},
    {'slug': 'revistas', 'label': 'Revistas', 'color_variant': 'tertiary'},
    {'slug': 'ensayos', 'label': 'Ensayos', 'color_variant': 'secondary'},
]

REGIONS = [
    {'name': 'Arequipa', 'code': '040'},
    {'name': 'Cusco', 'code': '080'},
    {'name': 'Loreto', 'code': '160'},
    {'name': 'Puno', 'code': '210'},
    {'name': 'La Libertad', 'code': '130'},
    {'name': 'Piura', 'code': '200'},
    {'name': 'Ayacucho', 'code': '050'},
    {'name': 'Lima', 'code': '150'},
]

AUTHORS = [
    {'key': 'aut-1', 'name': 'Marisol Quintana', 'bio': 'Ensayista y crítica literaria arequipeña.', 'region': 'Arequipa'},
    {'key': 'aut-2', 'name': 'Renzo Idrogo', 'bio': 'Cronista y editor. Escribe sobre oralidad amazónica.', 'region': 'Loreto'},
    {'key': 'aut-3', 'name': 'Ximena Roca', 'bio': 'Poeta y docente universitaria.', 'region': 'Cusco'},
    {'key': 'aut-4', 'name': 'Diego Salvatierra', 'bio': 'Investigador de narrativa regional andina.', 'region': 'Puno'},
    {'key': 'aut-5', 'name': 'Carla Núñez', 'bio': 'Periodista cultural, colaboradora habitual.', 'region': 'Lima'},
    {'key': 'aut-6', 'name': 'Fernando Achata', 'bio': 'Editor de la sección de Teoría Crítica.', 'region': 'La Libertad'},
]

TAGS = [
    ('Literatura regional', 'literatura-regional'),
    ('Oralidad', 'oralidad'),
    ('Poesía andina', 'poesia-andina'),
    ('Crítica literaria', 'critica-literaria'),
    ('Narrativa amazónica', 'narrativa-amazonica'),
    ('Teoría crítica', 'teoria-critica'),
    ('Editoriales independientes', 'editoriales-independientes'),
    ('Archivo cultural', 'archivo-cultural'),
    ('Migración y escritura', 'migracion-y-escritura'),
]

VOLUMES = [
    {'code': 'VOL. 04', 'title': 'Formas de la memoria en la narrativa post-conflicto', 'author': 'aut-6',
     'abstract': 'Un estudio sobre los modos en que la literatura peruana reciente elabora la memoria del conflicto armado interno.'},
    {'code': 'VOL. 03', 'title': 'Oralidad y escritura: tensiones en la crónica amazónica', 'author': 'aut-2',
     'abstract': 'Aproximación teórica a los cruces entre tradición oral y registro escrito en la crónica contemporánea de la Amazonía.'},
    {'code': 'VOL. 02', 'title': 'El sujeto andino en la poesía del siglo XXI', 'author': 'aut-3',
     'abstract': 'Lectura crítica de la construcción del sujeto andino en tres generaciones de poetas del sur peruano.'},
    {'code': 'VOL. 01', 'title': 'Editoriales independientes: cartografía de una década', 'author': 'aut-4',
     'abstract': 'Mapeo del ecosistema de editoriales independientes regionales entre 2014 y 2024.'},
]

ARTICLES = [
    {'slug': 'voces-regionales-literatura-peruana', 'title': 'Voces regionales: la literatura peruana fuera de Lima',
     'excerpt': 'Un recorrido por autores que construyen su obra desde los circuitos editoriales regionales.',
     'category': 'articulos', 'tags': ['literatura-regional', 'editoriales-independientes'], 'author': 'aut-1',
     'days_ago': 1, 'reading_time': 6, 'orientation': 'landscape', 'has_narration': True, 'region': 'Arequipa', 'status': 'published',
     'body': '<p>Un recorrido por autores que construyen su obra desde los circuitos editoriales regionales, lejos de la centralidad limeña.</p><p>El texto continúa explorando casos concretos de Arequipa, Cusco y Loreto.</p>'},
    {'slug': 'entrevista-ximena-roca-poesia-cusco', 'title': 'Ximena Roca: "La poesía andina no necesita traducirse al centro"',
     'excerpt': 'Conversamos con la poeta cusqueña sobre lengua, territorio y las editoriales que la publican.',
     'category': 'entrevistas', 'tags': ['poesia-andina', 'literatura-regional'], 'author': 'aut-5',
     'days_ago': 2, 'reading_time': 9, 'orientation': 'portrait', 'has_narration': False, 'region': 'Cusco', 'status': 'published',
     'youtube': 'https://www.youtube.com/embed/dQw4w9WgXcQ',
     'body': '<p>Conversamos con la poeta cusqueña sobre lengua, territorio y las editoriales que la publican.</p>'},
    {'slug': 'cronica-oralidad-amazonica', 'title': 'La crónica que aprendió a escuchar: oralidad en la Amazonía',
     'excerpt': 'Cómo un grupo de cronistas loretanos transforma el relato oral en literatura escrita sin traicionarlo.',
     'category': 'ensayos', 'tags': ['oralidad', 'narrativa-amazonica'], 'author': 'aut-2',
     'days_ago': 3, 'reading_time': 8, 'orientation': 'landscape', 'has_narration': True, 'region': 'Loreto', 'status': 'published',
     'body': '<p>Cómo un grupo de cronistas loretanos transforma el relato oral en literatura escrita sin traicionarlo.</p>'},
    {'slug': 'resena-formas-de-la-memoria', 'title': 'Reseña: "Formas de la memoria" y la crítica del post-conflicto',
     'excerpt': 'Una lectura del volumen 04 de Teoría Crítica, dedicado a la narrativa post-conflicto armado interno.',
     'category': 'articulos', 'tags': ['critica-literaria', 'teoria-critica'], 'author': 'aut-6',
     'days_ago': 5, 'reading_time': 7, 'orientation': 'square', 'has_narration': False, 'region': None, 'status': 'published',
     'body': '<p>Una lectura del volumen 04 de Teoría Crítica, dedicado a la narrativa post-conflicto armado interno.</p>'},
    {'slug': 'editoriales-independientes-decada', 'title': 'Diez años de editoriales independientes en el sur andino',
     'excerpt': 'Cartografía de los sellos que sostienen la edición literaria fuera de la capital.',
     'category': 'ensayos', 'tags': ['editoriales-independientes', 'literatura-regional'], 'author': 'aut-4',
     'days_ago': 6, 'reading_time': 10, 'orientation': 'landscape', 'has_narration': False, 'region': 'Puno', 'status': 'published',
     'body': '<p>Cartografía de los sellos que sostienen la edición literaria fuera de la capital.</p>'},
    {'slug': 'entrevista-renzo-idrogo-cronica', 'title': 'Renzo Idrogo: "Escribir crónica en la selva es escribir contra el olvido"',
     'excerpt': 'El cronista habla de su método de trabajo y del archivo oral que construye desde Iquitos.',
     'category': 'entrevistas', 'tags': ['oralidad', 'archivo-cultural'], 'author': 'aut-5',
     'days_ago': 8, 'reading_time': 11, 'orientation': 'portrait', 'has_narration': True, 'region': 'Loreto', 'status': 'published',
     'spotify': 'https://open.spotify.com/embed/episode/placeholder',
     'body': '<p>El cronista habla de su método de trabajo y del archivo oral que construye desde Iquitos.</p>'},
    {'slug': 'migracion-escritura-diaspora', 'title': 'Escribir desde la diáspora: migración y literatura peruana',
     'excerpt': 'Autores migrantes reflexionan sobre lengua, distancia y pertenencia en su escritura.',
     'category': 'articulos', 'tags': ['migracion-y-escritura', 'literatura-regional'], 'author': 'aut-3',
     'days_ago': 11, 'reading_time': 8, 'orientation': 'landscape', 'has_narration': False, 'region': 'Lima', 'status': 'published',
     'body': '<p>Autores migrantes reflexionan sobre lengua, distancia y pertenencia en su escritura.</p>'},
    {'slug': 'teoria-critica-sujeto-andino', 'title': 'El sujeto andino como categoría crítica en la poesía reciente',
     'excerpt': 'Ensayo teórico sobre las tensiones identitarias en tres generaciones de poetas del sur.',
     'category': 'ensayos', 'tags': ['teoria-critica', 'poesia-andina'], 'author': 'aut-3',
     'days_ago': 13, 'reading_time': 12, 'orientation': 'portrait', 'has_narration': False, 'region': 'Cusco', 'status': 'published',
     'body': '<p>Ensayo teórico sobre las tensiones identitarias en tres generaciones de poetas del sur.</p>'},
    {'slug': 'entrevista-carla-nunez-periodismo-cultural', 'title': 'Carla Núñez y el oficio de cubrir cultura desde las regiones',
     'excerpt': 'Una conversación sobre las dificultades de sostener el periodismo cultural fuera de Lima.',
     'category': 'entrevistas', 'tags': ['literatura-regional', 'archivo-cultural'], 'author': 'aut-6',
     'days_ago': 16, 'reading_time': 7, 'orientation': 'portrait', 'has_narration': False, 'region': 'La Libertad', 'status': 'published',
     'body': '<p>Una conversación sobre las dificultades de sostener el periodismo cultural fuera de Lima.</p>'},
    {'slug': 'cronica-ayacucho-archivo-textil', 'title': 'El archivo textil como narrativa: crónica desde Ayacucho',
     'excerpt': 'Una crónica sobre tejedoras que documentan memoria a través del textil y la palabra.',
     'category': 'ensayos', 'tags': ['archivo-cultural', 'literatura-regional'], 'author': 'aut-1',
     'days_ago': 18, 'reading_time': 9, 'orientation': 'landscape', 'has_narration': False, 'region': 'Ayacucho', 'status': 'published',
     'body': '<p>Una crónica sobre tejedoras que documentan memoria a través del textil y la palabra.</p>'},
    {'slug': 'programado-critica-literaria-noviembre', 'title': 'Balance de crítica literaria: lo que viene en el próximo número',
     'excerpt': 'Adelanto editorial programado para el próximo mes.',
     'category': 'articulos', 'tags': ['critica-literaria'], 'author': 'aut-6',
     'days_ago': 0, 'reading_time': 5, 'orientation': 'landscape', 'has_narration': False, 'region': None, 'status': 'scheduled',
     'scheduled_days_ago': -10,
     'body': ''},
    {'slug': 'borrador-nota-editorial', 'title': 'Nota editorial en construcción',
     'excerpt': 'Texto aún en revisión por el equipo editorial.',
     'category': 'articulos', 'tags': [], 'author': 'aut-5',
     'days_ago': 0, 'reading_time': 2, 'orientation': 'square', 'has_narration': False, 'region': None, 'status': 'draft',
     'body': ''},
]


class Command(BaseCommand):
    help = 'Carga el contenido de demostración equivalente al lib/api.ts del frontend Astro.'

    def handle(self, *args, **options):
        user, was_created = User.objects.get_or_create(
            username=DEMO_USER['username'],
            defaults={'email': DEMO_USER['email'], 'is_staff': True, 'is_superuser': True},
        )
        if was_created:
            user.set_password(DEMO_USER['password'])
            user.save()
        self.stdout.write(self.style.SUCCESS(f'Usuario demo: {"creado" if was_created else "ya existía"} ({DEMO_USER["email"]})'))

        regions_by_name = {}
        for r in REGIONS:
            region, _ = Region.objects.get_or_create(code=r['code'], defaults={'name': r['name']})
            regions_by_name[r['name']] = region
        self.stdout.write(self.style.SUCCESS(f'Regiones: {len(regions_by_name)}'))

        categories_by_slug = {}
        for c in CATEGORIES:
            category, _ = Category.objects.get_or_create(
                slug=c['slug'], defaults={'label': c['label'], 'color_variant': c['color_variant']}
            )
            categories_by_slug[c['slug']] = category
        self.stdout.write(self.style.SUCCESS(f'Categorías: {len(categories_by_slug)}'))

        authors_by_key = {}
        for a in AUTHORS:
            author, _ = Author.objects.get_or_create(
                name=a['name'], defaults={'bio': a['bio'], 'region': regions_by_name.get(a['region'])}
            )
            authors_by_key[a['key']] = author
        self.stdout.write(self.style.SUCCESS(f'Autores: {len(authors_by_key)}'))

        tags_by_slug = {}
        for label, slug in TAGS:
            t, _ = Tag.objects.get_or_create(slug=slug, defaults={'label': label})
            tags_by_slug[slug] = t
        self.stdout.write(self.style.SUCCESS(f'Etiquetas: {len(tags_by_slug)}'))

        for v in VOLUMES:
            Volume.objects.get_or_create(
                code=v['code'],
                defaults={'title': v['title'], 'author': authors_by_key[v['author']], 'abstract': v['abstract']},
            )
        self.stdout.write(self.style.SUCCESS(f'Volúmenes: {len(VOLUMES)}'))

        created = 0
        for item in ARTICLES:
            article, was_created = Article.objects.get_or_create(
                slug=item['slug'],
                defaults={
                    'title': item['title'],
                    'excerpt': item['excerpt'],
                    'body': item['body'],
                    'category': categories_by_slug[item['category']],
                    'author': authors_by_key[item['author']],
                    'region': regions_by_name.get(item['region']) if item['region'] else None,
                    'published_at': days_ago(item['days_ago']),
                    'scheduled_for': days_ago(item['scheduled_days_ago']) if item.get('scheduled_days_ago') is not None else None,
                    'reading_time_minutes': item['reading_time'],
                    'cover_image_orientation': item['orientation'],
                    'has_narration': item['has_narration'],
                    'youtube_embed_url': item.get('youtube', ''),
                    'spotify_embed_url': item.get('spotify', ''),
                    'status': item['status'],
                },
            )
            if was_created:
                created += 1
                if item['tags']:
                    article.tags.set([tags_by_slug[slug] for slug in item['tags']])
        self.stdout.write(self.style.SUCCESS(f'Artículos: {created} nuevos (de {len(ARTICLES)} definidos).'))

        self.stdout.write(self.style.SUCCESS('Listo.'))
