"""
Normaliza URLs de YouTube/Spotify que un editor pega tal cual las copia del
navegador (`youtube.com/watch?v=...`, `youtu.be/...`, un link normal de
`open.spotify.com/track|episode|show/...`) al único formato que en verdad se
puede meter en un <iframe>: `/embed/...`. Sin esto, YouTube/Spotify rechazan
la conexión (X-Frame-Options) porque sus páginas normales no son embebibles.

Se usa desde Article.save() y Category.save() — así no importa qué pegue el
editor en el panel, siempre queda guardado en el formato correcto.
"""
import re

_YOUTUBE_ID_RE = re.compile(r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{6,})')
_SPOTIFY_RE = re.compile(r'open\.spotify\.com/(?:embed/)?(track|episode|show|album|playlist)/([A-Za-z0-9]+)')


def normalize_youtube_embed_url(url: str) -> str:
    if not url:
        return url
    match = _YOUTUBE_ID_RE.search(url)
    if not match:
        return url
    return f'https://www.youtube.com/embed/{match.group(1)}'


def normalize_spotify_embed_url(url: str) -> str:
    if not url:
        return url
    match = _SPOTIFY_RE.search(url)
    if not match:
        return url
    kind, item_id = match.group(1), match.group(2)
    return f'https://open.spotify.com/embed/{kind}/{item_id}'
