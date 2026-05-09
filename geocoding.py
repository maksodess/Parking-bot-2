"""
Модуль для геокодирования через Yandex Geocoder API
Замена для небезопасного Nominatim OSM
"""
import aiohttp
import asyncio
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# API ключ из переменных окружения
YANDEX_API_KEY = os.environ.get("YANDEX_GEOCODER_API_KEY", "")

# Константы
GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"
TIMEOUT = 5  # секунды
VARNA_CENTER = (43.2141, 27.9147)  # lat, lon
MAX_DISTANCE_KM = 50  # Максимальное расстояние от Варны


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Вычисляет расстояние между двумя точками на Земле (в километрах).
    Формула Haversine.
    """
    from math import radians, sin, cos, sqrt, atan2
    
    R = 6371  # Радиус Земли в км
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    return R * c


async def geocode_address(
    address: str, 
    lang: str = "ru_RU",
    validate_varna: bool = True
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Прямое геокодирование: адрес → координаты.
    
    Args:
        address: Адрес для поиска (например: "ул. Цар Симеон I 15")
        lang: Язык ответа (ru_RU, bg_BG, en_US)
        validate_varna: Проверять ли что адрес в пределах 50км от Варны
    
    Returns:
        Tuple[lat, lon, formatted_address] или (None, None, None) при ошибке
    
    Examples:
        >>> lat, lon, addr = await geocode_address("бул. Приморски 42")
        >>> print(f"{lat}, {lon}: {addr}")
        42.6977, 27.7151: Болгария, Варна, бул. Приморски, 42
    """
    if not YANDEX_API_KEY:
        logger.error("YANDEX_GEOCODER_API_KEY is not set in environment variables!")
        return None, None, None
    
    # Добавляем "Варна" к запросу для лучшей точности
    search_query = f"{address}, Варна, Болгария" if "варна" not in address.lower() else address
    
    params = {
        "apikey": YANDEX_API_KEY,
        "geocode": search_query,
        "format": "json",
        "results": 1,  # Только лучший результат
        "lang": lang,
        "kind": "house"  # Приоритет: конкретные здания
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GEOCODER_URL, 
                params=params, 
                timeout=aiohttp.ClientTimeout(total=TIMEOUT)
            ) as resp:
                
                # Проверка статуса
                if resp.status == 403:
                    logger.error("Yandex API: 403 Forbidden - check API key or allowlist")
                    return None, None, None
                
                if resp.status == 429:
                    logger.warning("Yandex API: Rate limit exceeded")
                    return None, None, None
                
                if resp.status != 200:
                    logger.error(f"Yandex API returned status {resp.status}")
                    return None, None, None
                
                data = await resp.json()
                
                # Парсинг ответа
                geo_objects = data.get("response", {}).get("GeoObjectCollection", {})
                members = geo_objects.get("featureMember", [])
                
                if not members:
                    logger.info(f"No geocoding results for: {address}")
                    return None, None, None
                
                geo_object = members[0]["GeoObject"]
                
                # ВНИМАНИЕ: Yandex возвращает координаты в формате "lon lat"!
                pos = geo_object["Point"]["pos"].split()
                longitude, latitude = float(pos[0]), float(pos[1])
                
                # Форматированный адрес
                formatted = geo_object["metaDataProperty"]["GeocoderMetaData"]["text"]
                
                # Убираем "Болгария, " из начала для компактности
                if formatted.startswith("Болгария, "):
                    formatted = formatted[10:]
                
                # Проверка точности
                precision = geo_object["metaDataProperty"]["GeocoderMetaData"].get("precision", "other")
                if precision not in ["exact", "number", "near", "range"]:
                    logger.warning(f"Low precision geocoding: {precision} for {address}")
                
                # Валидация расстояния до Варны
                if validate_varna:
                    distance = haversine(latitude, longitude, *VARNA_CENTER)
                    if distance > MAX_DISTANCE_KM:
                        logger.info(f"Address too far from Varna: {distance:.1f}km")
                        return None, None, None
                
                logger.info(f"Geocoded: '{address}' → {latitude}, {longitude}")
                return latitude, longitude, formatted
                
    except asyncio.TimeoutError:
        logger.error(f"Yandex Geocoder timeout for: {address}")
        return None, None, None
    
    except aiohttp.ClientError as e:
        logger.error(f"Network error during geocoding: {e}")
        return None, None, None
    
    except Exception as e:
        logger.error(f"Unexpected geocoding error: {e}", exc_info=True)
        return None, None, None


async def reverse_geocode(
    lat: float, 
    lon: float, 
    lang: str = "ru_RU"
) -> Optional[str]:
    """
    Обратное геокодирование: координаты → адрес.
    Используется когда пользователь отправляет геолокацию.
    
    Args:
        lat: Широта
        lon: Долгота
        lang: Язык ответа (ru_RU, bg_BG, en_US)
    
    Returns:
        Форматированный адрес или None при ошибке
    
    Examples:
        >>> address = await reverse_geocode(43.2141, 27.9147)
        >>> print(address)
        Варна, площад Независимост
    """
    if not YANDEX_API_KEY:
        logger.error("YANDEX_GEOCODER_API_KEY is not set!")
        return None
    
    # ВНИМАНИЕ: Для reverse geocoding формат "lon,lat"!
    params = {
        "apikey": YANDEX_API_KEY,
        "geocode": f"{lon},{lat}",  # lon, lat (не lat, lon!)
        "format": "json",
        "results": 1,
        "lang": lang,
        "kind": "house"  # Искать конкретное здание
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GEOCODER_URL, 
                params=params, 
                timeout=aiohttp.ClientTimeout(total=TIMEOUT)
            ) as resp:
                
                if resp.status != 200:
                    logger.error(f"Reverse geocoding failed: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                
                members = data.get("response", {}).get("GeoObjectCollection", {}).get("featureMember", [])
                
                if not members:
                    logger.info(f"No reverse geocoding result for: {lat}, {lon}")
                    return None
                
                geo_object = members[0]["GeoObject"]
                address = geo_object["metaDataProperty"]["GeocoderMetaData"]["text"]
                
                # Убираем "Болгария, " из начала
                if address.startswith("Болгария, "):
                    address = address[10:]
                
                logger.info(f"Reverse geocoded: {lat}, {lon} → '{address}'")
                return address
                
    except asyncio.TimeoutError:
        logger.error("Reverse geocoding timeout")
        return None
    
    except Exception as e:
        logger.error(f"Reverse geocoding error: {e}", exc_info=True)
        return None


async def validate_varna_location(lat: float, lon: float) -> Tuple[bool, float]:
    """
    Проверяет, находится ли точка в пределах допустимого радиуса от Варны.
    
    Args:
        lat: Широта
        lon: Долгота
    
    Returns:
        Tuple[is_valid, distance_km]
    
    Examples:
        >>> is_valid, dist = await validate_varna_location(43.2141, 27.9147)
        >>> print(f"Valid: {is_valid}, Distance: {dist:.1f}km")
        Valid: True, Distance: 0.0km
    """
    distance = haversine(lat, lon, *VARNA_CENTER)
    is_valid = distance <= MAX_DISTANCE_KM
    return is_valid, distance


# ============================================================================
# Тестовая функция (запускать напрямую для проверки)
# ============================================================================

async def test_geocoder():
    """
    Тестирование геокодера.
    Запуск: python3 geocoding.py
    """
    print("=" * 60)
    print("ТЕСТ YANDEX GEOCODER API")
    print("=" * 60)
    
    if not YANDEX_API_KEY:
        print("❌ ОШИБКА: Переменная YANDEX_GEOCODER_API_KEY не установлена!")
        print("   Экспортируйте: export YANDEX_GEOCODER_API_KEY='ваш_ключ'")
        return
    
    print(f"✅ API ключ: {YANDEX_API_KEY[:20]}...")
    print()
    
    # Тест 1: Прямое геокодирование (русский адрес)
    print("Тест 1: Геокодирование русского адреса")
    print("-" * 60)
    address = "бул. Приморски 42"
    lat, lon, formatted = await geocode_address(address, lang="ru_RU")
    
    if lat:
        print(f"✅ Адрес: {address}")
        print(f"   Координаты: {lat:.6f}, {lon:.6f}")
        print(f"   Форматированный: {formatted}")
    else:
        print(f"❌ Не удалось найти адрес: {address}")
    print()
    
    # Тест 2: Прямое геокодирование (болгарский адрес)
    print("Тест 2: Геокодирование болгарского адреса")
    print("-" * 60)
    address_bg = "ул. Цар Симеон I 15"
    lat2, lon2, formatted2 = await geocode_address(address_bg, lang="bg_BG")
    
    if lat2:
        print(f"✅ Адрес: {address_bg}")
        print(f"   Координаты: {lat2:.6f}, {lon2:.6f}")
        print(f"   Форматированный: {formatted2}")
    else:
        print(f"❌ Не удалось найти адрес: {address_bg}")
    print()
    
    # Тест 3: Обратное геокодирование
    print("Тест 3: Обратное геокодирование (координаты → адрес)")
    print("-" * 60)
    test_lat, test_lon = 43.2141, 27.9147  # Центр Варны
    address_reverse = await reverse_geocode(test_lat, test_lon)
    
    if address_reverse:
        print(f"✅ Координаты: {test_lat}, {test_lon}")
        print(f"   Адрес: {address_reverse}")
    else:
        print(f"❌ Не удалось определить адрес для координат")
    print()
    
    # Тест 4: Валидация расстояния
    print("Тест 4: Проверка расстояния от Варны")
    print("-" * 60)
    
    # Точка в Варне (должна пройти)
    is_valid1, dist1 = await validate_varna_location(43.2141, 27.9147)
    print(f"Центр Варны: {is_valid1} (расстояние: {dist1:.1f}км)")
    
    # Точка в Софии (не должна пройти)
    is_valid2, dist2 = await validate_varna_location(42.6977, 23.3219)
    print(f"София: {is_valid2} (расстояние: {dist2:.1f}км)")
    
    print()
    print("=" * 60)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 60)


if __name__ == "__main__":
    # Запуск тестов
    asyncio.run(test_geocoder())
