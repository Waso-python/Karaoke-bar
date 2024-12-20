import csv
import os
from typing import List, Dict
from .models import Song


class SongLoader:
    _instance = None
    _songs: List[Song] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SongLoader, cls).__new__(cls)
            cls._instance._load_songs()
        return cls._instance

    def _load_songs(self):
        songs_file = os.path.join(os.path.dirname(__file__), "songs.csv")
        print(f"Loading songs from: {songs_file}")

        try:
            with open(songs_file, 'r', encoding='cp1251') as file:
                next(file)
                csv_reader = csv.reader(file, delimiter=';')
                for row in csv_reader:
                    if len(row) >= 4:
                        try:
                            has_backing = bool(row[3].strip()) if len(
                                row) > 3 else False
                            self._songs.append(Song(
                                id=int(row[0]) if row[0].strip() else 0,
                                title=row[1].strip(),
                                artist=row[2].strip(),
                                has_backing=has_backing,
                                type=row[4].strip() if len(row) > 4 else None
                            ))
                        except Exception as e:
                            print(f"Ошибка при обработке строки {row}: {e}")
                            continue
        except FileNotFoundError:
            print(f"❌ Файл не найден: {songs_file}")
        except Exception as e:
            print(f"❌ Ошибка при чтении файла: {e}")

    @property
    def songs(self) -> List[Song]:
        return self._songs

    def reload_songs(self):
        """Перезагрузка списка песен"""
        self._songs = []
        self._load_songs()


# Создаем единственный экземпляр загрузчика песен
song_loader = SongLoader()
SONGS = song_loader.songs
