
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


LIST_URL = "https://torgi.org/index.php?class=Auction&action=List&mod=Open&AuctionType=All"
BASE_URL = "https://torgi.org"


def fetch_html_from_web(url: str = LIST_URL) -> str:
    # Скачивает HTML-страницу со списком торгов.
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    # Страница может быть не в utf-8, поэтому используем apparent_encoding
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def read_html_from_file(path: Path) -> str:
    #  Читает HTML из локального файла.
    return path.read_text(encoding="utf-8")


def parse_price(text: str) -> Decimal:

    # Преобразует цену из строкового формата в число (Decimal).

    cleaned = (
        text.replace("\xa0", " ")
        .replace("руб.", "")
        .replace("руб", "")
        .replace(" ", "")
        .replace(",", ".")
        .strip()
    )
    if not cleaned:
        raise ValueError("Пустая цена")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Не удалось разобрать цену '{text}'") from exc


def parse_lots(html: str) -> List[Dict[str, object]]:
    """
    Разбирает HTML и возвращает список лотов.

    Каждый лот — словарь:
    {
        "code": str,
        "title": str,
        "price": Decimal,
        "url": str | None,
    }
    """
    soup = BeautifulSoup(html, "lxml")
    lots: List[Dict[str, object]] = []

    # Находим все строки, где:
    # - есть минимум 7 ячеек;
    # - в первой ячейке — числовой код лота.
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 7:
            continue

        code_text = cells[0].get_text(" ", strip=True)
        if not code_text.isdigit():
            continue  # это не строка с лотом

        code = code_text

        # Вторая колонка — название + ссылка
        name_cell = cells[1]
        title = name_cell.get_text(" ", strip=True)
        link_tag = name_cell.find("a", href=True)
        url = urljoin(BASE_URL, link_tag["href"]) if link_tag else None

        # Шестая колонка (index 5) — начальная цена
        price_text = cells[5].get_text(" ", strip=True)
        try:
            price = parse_price(price_text)
        except ValueError:
            # если цену не удалось распарсить — пропускаем лот
            continue

        lots.append(
            {
                "code": code,
                "title": title,
                "price": price,
                "url": url,
            }
        )

    return lots


def filter_lots_by_price(
    lots: List[Dict[str, object]],
    min_price: Optional[Decimal],
    max_price: Optional[Decimal],
) -> List[Dict[str, object]]:
    """Фильтрует лоты по диапазону цен."""
    if min_price is None and max_price is None:
        return lots

    def in_range(price: Decimal) -> bool:
        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False
        return True

    return [lot for lot in lots if in_range(lot["price"])]


def ask_price(prompt: str) -> Optional[Decimal]:
  
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        try:
            return parse_price(raw)
        except ValueError:
            print("Не удалось распознать число, попробуйте ещё раз.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Парсер лотов с сайта torgi.org (список торгов всех типов). "
            "Извлекает название, цену и ссылку на лот, "
            "сортирует по цене и фильтрует по введённому диапазону."
        )
    )
    parser.add_argument(
        "--file",
        type=str,
        help=(
            "Путь к локальному HTML-файлу со списком торгов. "
            "Если не указан, HTML будет скачан с сайта torgi.org."
        ),
    )
    parser.add_argument(
        "--min-price",
        type=str,
        help="Минимальная цена фильтрации (например 500000 или 1 200 000.00). Можно не указывать.",
    )
    parser.add_argument(
        "--max-price",
        type=str,
        help="Максимальная цена фильтрации. Можно не указывать.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="lots.json",
        help="Имя JSON-файла для сохранения результата (по умолчанию lots.json).",
    )

    # Use parse_known_args to ignore arguments passed by the Colab kernel
    args, unknown = parser.parse_known_args()

    # Источник HTML: либо файл, либо веб-страница
    if args.file:
        html = read_html_from_file(Path(args.file))
    else:
        html = fetch_html_from_web()

    lots = parse_lots(html)

    # Разбор диапазона цен из аргументов
    def parse_price_arg(raw: Optional[str]) -> Optional[Decimal]:
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            return None
        return parse_price(raw)

    min_price = parse_price_arg(args.min_price)
    max_price = parse_price_arg(args.max_price)

    # Если в аргументах не задано — спрашиваем у пользователя
    if min_price is None and max_price is None:
        print("Введите диапазон цен (можно оставить пустым):")
        min_price = ask_price("Минимальная цена (руб), пусто == без ограничения: ")
        max_price = ask_price("Максимальная цена (руб), пусто == без ограничения: ")

    filtered = filter_lots_by_price(lots, min_price, max_price)

    # Сортировка от самого дорогого к самому дешёвому
    sorted_lots = sorted(filtered, key=lambda lot: lot["price"], reverse=True)

    # Вывод в консоль: цена | название | ссылка
    for lot in sorted_lots:
        price_str = f"{lot['price']}"
        print(f"{price_str} руб. | {lot['title']} | {lot['url'] or '-'}")

    # Сохранение результата в JSON (по желанию, для себя)
    json_ready = [
        {
            "code": lot["code"],
            "title": lot["title"],
            "price": float(lot["price"]), # Convert Decimal to float for JSON serialization
            "url": lot["url"],
        }
        for lot in sorted_lots
    ]
    Path(args.output).write_text(
        json.dumps(json_ready, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
