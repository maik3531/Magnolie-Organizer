#!/usr/bin/env python3
"""Merge only manually authored identifier-sharing strings in all 20 locales."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
IDS = ("share", "explanation", "phone", "serial", "imei", "off", "permission", "restricted", "subscription", "unavailable")
TEXT = {
    "en": ("Share own phone identifiers", "Only on request from your own paired computer, for 60 seconds, without saving: the default voice SIM number and, if Android permits, serial number and IMEI. Android 10 and later restrict hardware identifiers for ordinary apps. Phone-number permission is optional; no special role is requested.", "Own phone number (default voice SIM)", "Device serial number", "Device IMEI", "Device identifier sharing is off.", "Device identifier permission is missing.", "Android restricts this device identifier.", "No default voice subscription is available.", "This device identifier is unavailable."),
    "de": ("Kennungen des eigenen Telefons teilen", "Nur auf Anfrage des eigenen gekoppelten Rechners, für 60 Sekunden, ohne Speicherung: die Nummer der Standard-Sprach-SIM und, soweit Android es erlaubt, Seriennummer und IMEI. Ab Android 10 sind Hardwarekennungen für gewöhnliche Apps eingeschränkt. Die Rufnummernberechtigung ist freiwillig; es wird keine Sonderrolle angefordert.", "Eigene Rufnummer (Standard-Sprach-SIM)", "Geräteseriennummer", "Geräte-IMEI", "Das Teilen der Gerätekennungen ist ausgeschaltet.", "Die Berechtigung für Gerätekennungen fehlt.", "Android beschränkt diese Gerätekennung.", "Keine Standard-Sprach-SIM verfügbar.", "Diese Gerätekennung ist nicht verfügbar."),
    "fr": ("Partager les identifiants de mon téléphone", "Uniquement sur demande de votre ordinateur associé, pendant 60 secondes, sans enregistrement : le numéro de la SIM vocale par défaut et, si Android le permet, le numéro de série et l’IMEI. Depuis Android 10, les identifiants matériels sont restreints pour les applications ordinaires. L’autorisation du numéro est facultative ; aucun rôle spécial n’est demandé.", "Mon numéro (SIM vocale par défaut)", "Numéro de série de l’appareil", "IMEI de l’appareil", "Le partage des identifiants est désactivé.", "L’autorisation des identifiants est manquante.", "Android restreint cet identifiant.", "Aucun abonnement vocal par défaut disponible.", "Cet identifiant est indisponible."),
    "es": ("Compartir identificadores de mi teléfono", "Solo a petición de su propio ordenador vinculado, durante 60 segundos, sin guardar: el número de la SIM de voz predeterminada y, si Android lo permite, el número de serie y el IMEI. Desde Android 10 se restringen los identificadores de hardware para las aplicaciones normales. El permiso del número es opcional; no se solicita ningún rol especial.", "Mi número (SIM de voz predeterminada)", "Número de serie del dispositivo", "IMEI del dispositivo", "El uso compartido de identificadores está desactivado.", "Falta el permiso para identificadores.", "Android restringe este identificador.", "No hay suscripción de voz predeterminada disponible.", "Este identificador no está disponible."),
    "it": ("Condividi gli identificativi del mio telefono", "Solo su richiesta del proprio computer associato, per 60 secondi, senza salvare: il numero della SIM vocale predefinita e, se Android lo consente, numero di serie e IMEI. Da Android 10 gli identificativi hardware sono limitati per le app ordinarie. Il permesso per il numero è facoltativo; non viene richiesto alcun ruolo speciale.", "Il mio numero (SIM vocale predefinita)", "Numero di serie del dispositivo", "IMEI del dispositivo", "La condivisione degli identificativi è disattivata.", "Manca il permesso per gli identificativi.", "Android limita questo identificativo.", "Nessun abbonamento vocale predefinito disponibile.", "Questo identificativo non è disponibile."),
    "nl": ("Identificatiegegevens van mijn telefoon delen", "Alleen op verzoek van uw eigen gekoppelde computer, gedurende 60 seconden, zonder opslaan: het nummer van de standaard spraak-sim en, als Android het toestaat, serienummer en IMEI. Vanaf Android 10 zijn hardware-identificatiegegevens beperkt voor gewone apps. De nummermachtiging is optioneel; er wordt geen speciale rol aangevraagd.", "Mijn nummer (standaard spraak-sim)", "Serienummer van apparaat", "IMEI van apparaat", "Het delen van apparaatidentificatie is uitgeschakeld.", "De machtiging voor apparaatidentificatie ontbreekt.", "Android beperkt deze apparaatidentificatie.", "Geen standaard spraakabonnement beschikbaar.", "Deze apparaatidentificatie is niet beschikbaar."),
    "pt": ("Partilhar identificadores do meu telefone", "Apenas a pedido do seu próprio computador emparelhado, durante 60 segundos, sem guardar: o número do SIM de voz predefinido e, se o Android permitir, número de série e IMEI. Desde o Android 10, os identificadores de hardware são restritos para aplicações comuns. A permissão do número é opcional; não é pedida nenhuma função especial.", "O meu número (SIM de voz predefinido)", "Número de série do dispositivo", "IMEI do dispositivo", "A partilha de identificadores está desativada.", "Falta a permissão para identificadores.", "O Android restringe este identificador.", "Nenhuma subscrição de voz predefinida disponível.", "Este identificador está indisponível."),
    "ru": ("Передавать идентификаторы своего телефона", "Только по запросу своего сопряжённого компьютера, на 60 секунд, без сохранения: номер SIM для голосовых вызовов по умолчанию и, если Android разрешает, серийный номер и IMEI. Начиная с Android 10 аппаратные идентификаторы ограничены для обычных приложений. Разрешение на номер необязательно; специальные роли не запрашиваются.", "Свой номер (SIM для звонков по умолчанию)", "Серийный номер устройства", "IMEI устройства", "Передача идентификаторов отключена.", "Нет разрешения на идентификаторы.", "Android ограничивает этот идентификатор.", "Нет подписки для звонков по умолчанию.", "Этот идентификатор недоступен."),
    "cs": ("Sdílet identifikátory vlastního telefonu", "Pouze na žádost vlastního spárovaného počítače, na 60 sekund, bez uložení: číslo výchozí hlasové SIM a, pokud Android dovolí, sériové číslo a IMEI. Od Androidu 10 jsou hardwarové identifikátory pro běžné aplikace omezené. Oprávnění k číslu je volitelné; žádná zvláštní role se nevyžaduje.", "Vlastní číslo (výchozí hlasová SIM)", "Sériové číslo zařízení", "IMEI zařízení", "Sdílení identifikátorů je vypnuté.", "Chybí oprávnění k identifikátorům.", "Android omezuje tento identifikátor.", "Není dostupný výchozí hlasový tarif.", "Tento identifikátor není dostupný."),
    "pl": ("Udostępniaj identyfikatory własnego telefonu", "Tylko na żądanie własnego sparowanego komputera, przez 60 sekund, bez zapisywania: numer domyślnej karty SIM do rozmów oraz, jeśli Android pozwala, numer seryjny i IMEI. Od Androida 10 identyfikatory sprzętowe są ograniczone dla zwykłych aplikacji. Uprawnienie do numeru jest opcjonalne; specjalne role nie są żądane.", "Własny numer (domyślna karta SIM do rozmów)", "Numer seryjny urządzenia", "IMEI urządzenia", "Udostępnianie identyfikatorów jest wyłączone.", "Brak uprawnienia do identyfikatorów.", "Android ogranicza ten identyfikator.", "Brak domyślnej subskrypcji do rozmów.", "Ten identyfikator jest niedostępny."),
    "hsb": ("Identifikatory swójskeho telefona dźělić", "Jenož na naprašowanje swójskeho spřaženeho ličaka, na 60 sekund, bjez składowanja: čisło standardneje SIM za zawołanja a, jeli Android dowoli, serijowe čisło a IMEI. Wot Androida 10 su hardwarowe identifikatory za zwučene aplikacije wobmjezowane. Prawo za čisło je dobrowólne; žana wosebita róla so njepožada.", "Swójske čisło (standardna SIM za zawołanja)", "Serijowe čisło grata", "IMEI grata", "Dźělenje identifikatorow je wupinjene.", "Prawo za identifikatory faluje.", "Android tutón identifikator wobmjezuje.", "Žadyn standardny abonement za zawołanja k dispoziciji njeje.", "Tutón identifikator k dispoziciji njeje."),
    "da": ("Del min telefons identifikatorer", "Kun efter anmodning fra din egen parrede computer, i 60 sekunder, uden at gemme: nummeret på standard-SIM til opkald og, hvis Android tillader det, serienummer og IMEI. Fra Android 10 er hardwareidentifikatorer begrænset for almindelige apps. Tilladelse til nummeret er valgfri; ingen særlig rolle anmodes.", "Mit nummer (standard-SIM til opkald)", "Enhedens serienummer", "Enhedens IMEI", "Deling af enhedsidentifikatorer er slået fra.", "Tilladelse til enhedsidentifikatorer mangler.", "Android begrænser denne enhedsidentifikator.", "Intet standardabonnement til opkald er tilgængeligt.", "Denne enhedsidentifikator er utilgængelig."),
    "nb": ("Del identifikatorene til min telefon", "Bare på forespørsel fra din egen parede datamaskin, i 60 sekunder, uten lagring: nummeret til standard-SIM for anrop og, hvis Android tillater det, serienummer og IMEI. Fra Android 10 er maskinvareidentifikatorer begrenset for vanlige apper. Tillatelse til nummeret er valgfri; ingen særskilt rolle forespørres.", "Mitt nummer (standard-SIM for anrop)", "Enhetens serienummer", "Enhetens IMEI", "Deling av enhetsidentifikatorer er slått av.", "Tillatelse til enhetsidentifikatorer mangler.", "Android begrenser denne enhetsidentifikatoren.", "Intet standardabonnement for anrop er tilgjengelig.", "Denne enhetsidentifikatoren er utilgjengelig."),
    "hi": ("अपने फ़ोन के पहचानकर्ता साझा करें", "केवल अपने जुड़े कंप्यूटर के अनुरोध पर, 60 सेकंड के लिए, बिना सहेजे: डिफ़ॉल्ट वॉइस SIM का नंबर और, Android अनुमति दे तो, सीरियल नंबर और IMEI। Android 10 से सामान्य ऐप के लिए हार्डवेयर पहचानकर्ताओं पर प्रतिबंध हैं। नंबर की अनुमति वैकल्पिक है; कोई विशेष भूमिका नहीं माँगी जाती।", "अपना नंबर (डिफ़ॉल्ट वॉइस SIM)", "डिवाइस का सीरियल नंबर", "डिवाइस का IMEI", "डिवाइस पहचानकर्ता साझा करना बंद है।", "डिवाइस पहचानकर्ता की अनुमति नहीं है।", "Android इस डिवाइस पहचानकर्ता को प्रतिबंधित करता है।", "कोई डिफ़ॉल्ट वॉइस सदस्यता उपलब्ध नहीं है।", "यह डिवाइस पहचानकर्ता उपलब्ध नहीं है।"),
    "zh_CN": ("共享本机标识符", "仅应自己已配对电脑的请求显示 60 秒，不保存：默认语音 SIM 的号码，以及 Android 允许时的序列号和 IMEI。Android 10 及更高版本限制普通应用访问硬件标识符。电话号码权限为可选项；不会请求特殊角色。", "本机号码（默认语音 SIM）", "设备序列号", "设备 IMEI", "设备标识符共享已关闭。", "缺少设备标识符权限。", "Android 限制访问此设备标识符。", "没有可用的默认语音订阅。", "此设备标识符不可用。"),
    "ja": ("自分の電話の識別子を共有", "自分のペアリング済みパソコンからの要求時のみ、保存せずに 60 秒間表示します。対象は既定の音声 SIM の番号と、Android が許可する場合のシリアル番号および IMEI です。Android 10 以降では一般のアプリによるハードウェア識別子の取得が制限されます。電話番号の権限は任意で、特別な役割は要求しません。", "自分の番号（既定の音声 SIM）", "端末のシリアル番号", "端末の IMEI", "端末識別子の共有はオフです。", "端末識別子の権限がありません。", "Android がこの端末識別子を制限しています。", "既定の音声契約がありません。", "この端末識別子は利用できません。"),
    "ar": ("مشاركة معرّفات هاتفي", "فقط بطلب من حاسوبك المقترن، لمدة 60 ثانية، دون حفظ: رقم شريحة المكالمات الافتراضية، والرقم التسلسلي وIMEI إذا سمح Android. منذ Android 10 تُقيَّد معرّفات العتاد للتطبيقات العادية. إذن رقم الهاتف اختياري؛ لا يُطلب أي دور خاص.", "رقمي (شريحة المكالمات الافتراضية)", "الرقم التسلسلي للجهاز", "IMEI الجهاز", "مشاركة معرّفات الجهاز متوقفة.", "إذن معرّفات الجهاز غير ممنوح.", "يقيّد Android معرّف الجهاز هذا.", "لا يتوفر اشتراك مكالمات افتراضي.", "معرّف الجهاز هذا غير متاح."),
    "uk": ("Передавати ідентифікатори свого телефона", "Лише на запит власного сполученого комп’ютера, на 60 секунд, без збереження: номер типової SIM для дзвінків та, якщо Android дозволяє, серійний номер і IMEI. Від Android 10 апаратні ідентифікатори обмежені для звичайних застосунків. Дозвіл на номер необов’язковий; спеціальні ролі не запитуються.", "Власний номер (типова SIM для дзвінків)", "Серійний номер пристрою", "IMEI пристрою", "Передавання ідентифікаторів вимкнено.", "Немає дозволу на ідентифікатори.", "Android обмежує цей ідентифікатор.", "Немає типової підписки для дзвінків.", "Цей ідентифікатор недоступний."),
    "be": ("Перадаваць ідэнтыфікатары свайго тэлефона", "Толькі па запыце ўласнага спалучанага камп’ютара, на 60 секунд, без захавання: нумар стандартнай SIM для званкоў і, калі Android дазваляе, серыйны нумар і IMEI. Пачынаючы з Android 10 апаратныя ідэнтыфікатары абмежаваныя для звычайных праграм. Дазвол на нумар неабавязковы; спецыяльныя ролі не запытваюцца.", "Уласны нумар (стандартная SIM для званкоў)", "Серыйны нумар прылады", "IMEI прылады", "Перадача ідэнтыфікатараў выключана.", "Няма дазволу на ідэнтыфікатары.", "Android абмяжоўвае гэты ідэнтыфікатар.", "Няма стандартнай падпіскі для званкоў.", "Гэты ідэнтыфікатар недаступны."),
    "tr": ("Kendi telefonumun tanımlayıcılarını paylaş", "Yalnızca kendi eşleştirilmiş bilgisayarınızın isteğiyle, 60 saniye boyunca, kaydetmeden: varsayılan ses SIM numarası ve Android izin verirse seri numarası ile IMEI. Android 10 ve üzeri, normal uygulamalar için donanım tanımlayıcılarını kısıtlar. Numara izni isteğe bağlıdır; özel bir rol istenmez.", "Kendi numaram (varsayılan ses SIM’i)", "Cihaz seri numarası", "Cihaz IMEI’si", "Cihaz tanımlayıcısı paylaşımı kapalı.", "Cihaz tanımlayıcısı izni eksik.", "Android bu cihaz tanımlayıcısını kısıtlıyor.", "Varsayılan ses aboneliği yok.", "Bu cihaz tanımlayıcısı kullanılamıyor."),
}


def main():
    assert len(TEXT) == 20 and all(len(v) == len(IDS) for v in TEXT.values())
    spec = importlib.util.spec_from_file_location("catalog", ROOT / "magnolie-organizer/werkzeuge/desktop_pot_merge.py")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    for directory in (ROOT / "magnolie-organizer/po", ROOT / "magnolie-organizer-windows/app/po"):
        for path in [*directory.glob("*.po"), directory / "magnolie-organizer.pot"]:
            old = path.read_text(encoding="utf-8")
            entries = {e["msgid"]: e for e in parser.catalog(path) if not e["obsolete"]}
            values = TEXT[path.stem] if path.suffix == ".po" else ("",) * len(IDS)
            # The opt-in switch and explanation belong to Android, not desktop gettext.
            for key, value in zip(TEXT["en"][2:], values[2:]):
                if key in entries:
                    assert entries[key].get("msgstr") == value
                else:
                    old += '\n#. Device identifiers; manually translated.\nmsgid ' + json.dumps(key, ensure_ascii=False) + '\nmsgstr ' + json.dumps(value, ensure_ascii=False) + '\n'
            path.write_text(old, encoding="utf-8")
            mo = ROOT / "magnolie-organizer/locale" / path.stem / "LC_MESSAGES/magnolie-organizer.mo"
            if directory == ROOT / "magnolie-organizer/po" and path.suffix == ".po" and mo.parent.is_dir():
                subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(mo), str(path)], check=True)
    native = ROOT / "magnolie-organizer-windows/app/native-i18n.json"
    catalog = json.loads(native.read_text(encoding="utf-8"))
    for locale, values in TEXT.items():
        if locale != "en":
            catalog["locales"][locale].update(zip(TEXT["en"][2:], values[2:]))
            for key in TEXT["en"][:2]:
                catalog["locales"][locale].pop(key, None)
        suffix = "" if locale == "en" else "-" + ("zh-rCN" if locale == "zh_CN" else locale)
        path = ROOT / f"magnolie-notes/app/src/main/res/values{suffix}/strings.xml"
        content = path.read_text(encoding="utf-8")
        for name, value in zip(IDS, values):
            key = "device_identifiers_" + name
            if f'name="{key}"' not in content:
                content = content.replace("</resources>", f'    <string name="{key}">' + escape(value).replace("'", "\\'") + '</string>\n</resources>')
        path.write_text(content, encoding="utf-8")
        for root in ("magnolie-organizer/web", "magnolie-organizer-windows/app/web"):
            path = ROOT / root / "i18n" / (locale + ".js")
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            match = re.fullmatch(r'(window\.MagnolieI18n\.registerCatalog\("[^"]+", )(.*)(\);\s*)', content, re.S)
            assert match
            data = json.loads(match[2]); data["messages"].update(zip(TEXT["en"][2:], values[2:]))
            for key in TEXT["en"][:2]:
                data["messages"].pop(key, None)
            path.write_text(match[1] + json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + match[3], encoding="utf-8")
    native.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print("Merged 10 Android and 8 desktop identifier strings in 20 languages; unrelated entries preserved.")


if __name__ == "__main__":
    main()
