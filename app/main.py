from fastapi import FastAPI, HTTPException, Query
from typing import List, Optional
from enum import Enum
from .models import Song
from .utils import SONGS
from difflib import SequenceMatcher
import itertools

app = FastAPI(title="Поиск песен")


class SearchType(str, Enum):
    EXACT = "exact"        # Точное совпадение
    CONTAINS = "contains"  # Содержит подстроку
    SIMILAR = "similar"    # Похожие названия


def string_similarity(a: str, b: str) -> float:
    """Вычисляет схожесть двух строк"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def get_search_combinations(query: str) -> List[List[str]]:
    """Генерирует все возможные комбинации слов из запроса"""
    words = query.split()
    combinations = []

    # Генерируем комбинации разной длины
    for r in range(1, len(words) + 1):
        for combo in itertools.combinations(words, r):
            combinations.append(' '.join(combo))

    return combinations


def calculate_relevance_score(song: Song, query_parts: List[str], search_type: SearchType) -> float:
    """
    Вычисляет оценку релевантности для песни на основе совпадений в названии и исполнителе
    """
    max_title_score = 0
    max_artist_score = 0

    for part in query_parts:
        part = part.lower()
        title_lower = song.title.lower()
        artist_lower = song.artist.lower() if song.artist else ""

        # Проверяем совпадения в названии
        if search_type == SearchType.EXACT:
            title_score = 1.0 if part == title_lower else 0.0
        elif search_type == SearchType.CONTAINS:
            title_score = 0.8 if part in title_lower else 0.0
        else:  # SIMILAR
            title_score = string_similarity(part, title_lower)

        # Проверяем совпадения в исполнителе
        if artist_lower:
            if search_type == SearchType.EXACT:
                artist_score = 1.0 if part == artist_lower else 0.0
            elif search_type == SearchType.CONTAINS:
                artist_score = 0.8 if part in artist_lower else 0.0
            else:  # SIMILAR
                artist_score = string_similarity(part, artist_lower)
        else:
            artist_score = 0.0

        # Сохраняем максимальные оценки
        max_title_score = max(max_title_score, title_score)
        max_artist_score = max(max_artist_score, artist_score)

    # Итоговая оценка - взвешенная сумма лучших совпадений
    # Название имеет больший вес (0.6), чем исполнитель (0.4)
    return (max_title_score * 0.6) + (max_artist_score * 0.4)


@app.get("/songs/", response_model=List[Song])
async def get_all_songs():
    return SONGS


@app.get("/songs/search/", response_model=List[Song])
async def search_songs(
    query: str,
    search_type: SearchType = SearchType.SIMILAR,
    min_similarity: float = Query(0.3, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=100),
    with_backing: Optional[bool] = None
):
    """
    Улучшенный поиск песен:
    - поддерживает поиск по нескольким словам
    - ищет совпадения как в названии, так и среди исполнителей
    - ранжирует результаты по релевантности
    - может фильтровать по наличию бэка
    """
    if not query:
        raise HTTPException(
            status_code=400,
            detail="Поисковый запрос не может быть пустым"
        )

    query_parts = get_search_combinations(query)
    results = []

    for song in SONGS:
        # Проверяем фильтр по бэку, если он задан
        if with_backing is not None and song.has_backing != with_backing:
            continue

        # Вычисляем релевантность для каждой песни
        relevance = calculate_relevance_score(song, query_parts, search_type)

        # Если релевантность выше порога, добавляем песню в результаты
        if relevance >= min_similarity:
            song.similarity_score = relevance
            results.append(song)

    # Проверяем совпадение с исполнителем
    artist_query = query.lower()
    artist_results = [
        song for song in SONGS
        if song.artist and string_similarity(artist_query, song.artist.lower()) > 0.7
    ]
    results.extend(artist_results)

    # Удаляем дубликаты, если они появились
    results = list({song.id: song for song in results}.values())

    # Сортируем результаты по релевантности
    results.sort(key=lambda x: x.similarity_score, reverse=True)

    return results[:limit]


@app.get("/songs/by-artist/", response_model=List[Song])
async def search_by_artist(
    artist: str,
    limit: int = Query(50, ge=1, le=100)
):
    """Поиск всех песен конкретного исполнителя"""
    if not artist:
        raise HTTPException(
            status_code=400,
            detail="Имя исполнителя не может быть пустым"
        )

    artist = artist.lower()
    results = []

    for song in SONGS:
        if song.artist and artist in song.artist.lower():
            # Вычисляем точность совпадения для сортировки
            similarity = string_similarity(artist, song.artist)
            song.similarity_score = similarity
            results.append(song)

    # Сортируем по точности совпадения
    results.sort(key=lambda x: x.similarity_score, reverse=True)

    return results[:limit]


@app.get("/songs/with-backing/", response_model=List[Song])
async def get_songs_with_backing(
    limit: int = Query(50, ge=1, le=100)
):
    """Получение списка есен с бэком"""
    results = [song for song in SONGS if song.has_backing]
    return results[:limit]


@app.get("/songs/by-title/", response_model=List[Song])
async def search_by_title(
    title: str,
    min_similarity: float = Query(0.7, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=100)
):
    """Поиск песен по названию"""
    if not title:
        raise HTTPException(
            status_code=400,
            detail="Название песни не может быть пустым"
        )

    title = title.lower()
    results = []

    for song in SONGS:
        if song.title:
            # Вычисляем точность совпадения
            similarity = string_similarity(title, song.title.lower())
            if similarity >= min_similarity:
                song.similarity_score = similarity
                results.append(song)

    # Сортируем по точности совпадения
    results.sort(key=lambda x: x.similarity_score, reverse=True)

    return results[:limit]
