#!/usr/bin/env python3
"""Merge only the three manually authored call-alert strings; preserve other entries."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = (
    "Silence this alert",
    "Call controls unavailable. Check Android call permission; no dialer role is requested automatically.",
    "The call action expired or is no longer permitted.",
)
TRANSLATIONS = {
    "en": KEYS,
    "de": ("Diese Meldung stummschalten", "Anrufsteuerung nicht verfügbar. Prüfen Sie die Android-Anrufberechtigung; die Telefon-App-Rolle wird nicht automatisch angefordert.", "Die Anrufaktion ist abgelaufen oder nicht mehr erlaubt."),
    "fr": ("Masquer cette alerte", "Commandes d’appel indisponibles. Vérifiez l’autorisation d’appel Android ; le rôle d’application Téléphone n’est pas demandé automatiquement.", "L’action d’appel a expiré ou n’est plus autorisée."),
    "es": ("Silenciar esta alerta", "Controles de llamada no disponibles. Compruebe el permiso de llamadas de Android; no se solicita automáticamente el rol de aplicación de teléfono.", "La acción de llamada ha caducado o ya no está permitida."),
    "it": ("Silenzia questo avviso", "Controlli chiamata non disponibili. Verifica il permesso per le chiamate Android; il ruolo di app Telefono non viene richiesto automaticamente.", "L’azione di chiamata è scaduta o non è più consentita."),
    "nl": ("Deze melding dempen", "Oproepbediening niet beschikbaar. Controleer de Android-oproepmachtiging; de rol van telefoonapp wordt niet automatisch aangevraagd.", "De oproepactie is verlopen of niet meer toegestaan."),
    "pt": ("Silenciar este alerta", "Controlos de chamada indisponíveis. Verifique a permissão de chamadas do Android; a função de aplicação de telefone não é solicitada automaticamente.", "A ação de chamada expirou ou já não é permitida."),
    "ru": ("Отключить это оповещение", "Управление вызовом недоступно. Проверьте разрешение на звонки в Android; роль приложения «Телефон» автоматически не запрашивается.", "Срок действия команды вызова истёк или она больше не разрешена."),
    "cs": ("Ztišit toto upozornění", "Ovládání hovoru není dostupné. Zkontrolujte oprávnění k hovorům v Androidu; role telefonní aplikace se nevyžaduje automaticky.", "Platnost akce hovoru vypršela nebo již není povolena."),
    "pl": ("Wycisz to powiadomienie", "Sterowanie połączeniem jest niedostępne. Sprawdź uprawnienie do połączeń w Androidzie; rola aplikacji telefonu nie jest żądana automatycznie.", "Działanie dotyczące połączenia wygasło lub nie jest już dozwolone."),
    "hsb": ("Tutu zdźělenku zněmić", "Wodźenje zawołanja k dispoziciji njeje. Přepruwujće prawo za zawołanja w Androidźe; róla telefonoweje aplikacije so awtomatisce njepožada.", "Akcija zawołanja je spadnyła abo hižo dowolena njeje."),
    "da": ("Dæmp denne besked", "Opkaldsstyring er ikke tilgængelig. Kontrollér Androids opkaldstilladelse; rollen som telefonapp anmodes ikke automatisk.", "Opkaldshandlingen er udløbet eller er ikke længere tilladt."),
    "nb": ("Demp dette varselet", "Anropskontroller er utilgjengelige. Kontroller Androids anropstillatelse; rollen som telefonapp blir ikke forespurt automatisk.", "Anropshandlingen er utløpt eller er ikke lenger tillatt."),
    "hi": ("यह सूचना शांत करें", "कॉल नियंत्रण उपलब्ध नहीं हैं। Android की कॉल अनुमति जाँचें; डिफ़ॉल्ट फ़ोन ऐप की भूमिका अपने-आप नहीं माँगी जाती।", "कॉल कार्रवाई की समय-सीमा समाप्त हो गई है या अब इसकी अनुमति नहीं है।"),
    "zh_CN": ("关闭此提醒", "通话控制不可用。请检查 Android 通话权限；不会自动请求默认电话应用角色。", "通话操作已过期或不再获得许可。"),
    "ja": ("この通知を消す", "通話操作は利用できません。Android の通話権限を確認してください。既定の電話アプリの役割は自動では要求されません。", "通話操作の有効期限が切れたか、許可が取り消されました。"),
    "ar": ("إسكات هذا التنبيه", "التحكم بالمكالمة غير متاح. تحقق من إذن المكالمات في Android؛ لا يُطلب دور تطبيق الهاتف تلقائيًا.", "انتهت صلاحية إجراء المكالمة أو لم يعد مسموحًا به."),
    "uk": ("Вимкнути це сповіщення", "Керування викликом недоступне. Перевірте дозвіл на дзвінки в Android; роль застосунку «Телефон» автоматично не запитується.", "Термін дії команди виклику минув або вона більше не дозволена."),
    "be": ("Выключыць гэтае апавяшчэнне", "Кіраванне выклікам недаступнае. Праверце дазвол на званкі ў Android; роля праграмы «Тэлефон» аўтаматычна не запытваецца.", "Тэрмін дзеяння каманды выкліку скончыўся або яна больш не дазволена."),
    "tr": ("Bu uyarıyı sessize al", "Arama denetimleri kullanılamıyor. Android arama iznini kontrol edin; telefon uygulaması rolü otomatik olarak istenmez.", "Arama işleminin süresi doldu veya artık izin verilmiyor."),
}


def main():
    spec = importlib.util.spec_from_file_location("catalog", ROOT / "magnolie-organizer-2.0.0/werkzeuge/desktop_pot_merge.py")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    assert len(TRANSLATIONS) == 20 and all(len(values) == len(KEYS) for values in TRANSLATIONS.values())
    for directory in (ROOT / "magnolie-organizer-2.0.0/po", ROOT / "Magnolie-Organizer-Windows-2.0.0/app/po"):
        for path in [*directory.glob("*.po"), directory / "magnolie-organizer.pot"]:
            old = path.read_text(encoding="utf-8")
            entries = {entry["msgid"]: entry for entry in parser.catalog(path) if not entry["obsolete"]}
            values = TRANSLATIONS[path.stem] if path.suffix == ".po" else ("",) * len(KEYS)
            extra = ""
            for key, value in zip(KEYS, values):
                if key in entries:
                    assert entries[key].get("msgstr") == value, (path, key)
                    continue
                extra += "\n#. Call-state alerts; manually translated.\nmsgid " + json.dumps(key, ensure_ascii=False) + "\nmsgstr " + json.dumps(value, ensure_ascii=False) + "\n"
            if extra:
                path.write_text(old + extra, encoding="utf-8")
    path = ROOT / "Magnolie-Organizer-Windows-2.0.0/app/native-i18n.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    for locale, values in TRANSLATIONS.items():
        if locale == "en":
            continue
        entries = catalog["locales"][locale]
        for key, value in zip(KEYS, values):
            assert key not in entries or entries[key] == value
            entries[key] = value
    path.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print("Merged 3 call-alert strings in 20 languages; unrelated translations preserved.")


if __name__ == "__main__":
    main()
