from typing import TypedDict


class BankMeta(TypedDict):
    name: str
    icon_url: str


_BANK_MAP: dict[str, BankMeta] = {
    "VTB": {
        "name": "БАНК ВТБ",
        "icon_url":  "https://cdn.lifetechx.ru/icons/banks/icon_square/vtb_square.png",
    },
    "SBERBANK": {
        "name": "ПАО СБЕРБАНК",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/sberbank_square.png",
    },
    "TBANK": {
        "name": "АО «ТБАНК»",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/tbank_square.png",
    },
    "OZON": {
        "name": "ООО «ОЗОН БАНК»",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/ozon_square.png",
    },
    "PSB": {
        "name": "ПАО  БАНК ПСБ",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/unknown_square.png",
    },
    "WB": {
        "name": "ООО «ВАЙЛДБЕРРИЗ БАНК»",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/wb-bank_square.png",
    },
    "ALPHA": {
        "name": "АО «АЛЬФА-БАНК»",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/alfabank_square.png",
    },
    "SOVKOM": {
        "name": "ПАО «СОВКОМБАНК» ",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/sovcombank_square.png",
    },
    "DALNEVOSTOCHNIY": {
        "name": "АО «ДАЛЬНЕВОСТОЧНЫЙ БАНК»",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/dvbank_square.png",
    },
    "RAIFAIZEN": {
        "name": "РАЙФФАЙЗЕНБАНК",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/raiffeisen_square.png",
    },
    "PROMSVYAZBANK": {
        "name": "ПРОМСВЯЗЬБАНК",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/promsvyazbank_square.png",
    },
    "GAZPROMBANK": {
        "name": "БАНК ГПБ (АО)",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/gazprombank_square.png",
    },
    "AKBARS": {
        "name": "ПАО \"АК БАРС\" БАНК",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/akbars_square.png",
    }
    "UNKNOWN": {
        "name": "ДРУГОЙ БАНК",
        "icon_url": "https://cdn.lifetechx.ru/icons/banks/icon_square/unknown_square.png",
    },
}


def get_bank_meta(bank_code: str) -> BankMeta:
    normalized = str(bank_code).strip().upper()
    return _BANK_MAP.get(normalized, _BANK_MAP["UNKNOWN"])
