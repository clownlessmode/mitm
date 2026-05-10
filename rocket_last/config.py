# Центральные настройки для скриптов rocket_last.
# Меняйте значения здесь — они подтянутся в подключённых файлах.
last_balance = 5000
type = "SBP"  # SBP / CARD

# Настройки для добавления новой операции в историю.
history_new_payment_name = "Денис Н." # 2966 или "Ильсур Г."
history_new_payment_amount = 675294
direction = "OUTGOING"

details_new_payment_name = "ДЕНИС АЛЕКСЕЕВИЧ Н" # 2966 или "ИВАН ИВАНОВ И"

transaction_date = "2026-05-09"
transaction_time = "19:44:03"
# Сдвиг для поля transactionDateTime в API (как в ответах: +0300, +0000).
# Укажите ту же зону, в которой вы задаёте дату/время выше (Москва → +0300).
transaction_time_zone = "+0700"

sbp_telephone = "+7 900 108-32-49"

bank = "TBANK" # VTB / SBERBANK / TBANK / OZON / UNKNOWN / WB / ALPHA / SOVKOM / DALNEVOSTOCHNIY / RAIFAIZEN / 

card_number = "2200 **** **** 5206"


def transaction_tz_suffix() -> str:
    """Нормализует transaction_time_zone к суффиксу ISO как в API (+0300 без двоеточия)."""
    raw = str(transaction_time_zone).strip()
    if not raw:
        return "+0000"
    u = raw.upper()
    if u in ("Z", "UTC"):
        return "+0000"
    compact = raw.replace(":", "")
    if len(compact) == 5 and compact[0] in "+-" and compact[1:].isdigit():
        return compact
    return "+0000"