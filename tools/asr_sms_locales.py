#!/usr/bin/env python3
"""ASR SMS contract: manually authored translations, localized catalog merge only."""
import gettext
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TEXT = {
    "en": (
        "Review the exact SMS text for every recipient before confirming.",
        "Enabling this plan allows its overdue SMS to be sent while scheduling is on.",
        "Enable this SMS plan", "Confirm SMS plans", "Paused — review required", "Review and enable",
        "Restored pending plans stay paused until you review and enable each plan. Restoring contacts, calendar or notes does not change live SMS plans."),
    "de": (
        "Prüfen Sie vor der Bestätigung den genauen SMS-Text für jeden Empfänger.",
        "Wenn Sie diesen Plan aktivieren, kann seine überfällige SMS bei eingeschalteter Planung gesendet werden.",
        "Diesen SMS-Plan aktivieren", "SMS-Pläne bestätigen", "Pausiert — Prüfung erforderlich", "Prüfen und aktivieren",
        "Wiederhergestellte offene Pläne bleiben pausiert, bis Sie jeden Plan prüfen und aktivieren. Die Wiederherstellung von Kontakten, Kalender oder Notizen ändert keine laufenden SMS-Pläne."),
    "fr": (
        "Vérifiez le texte exact du SMS pour chaque destinataire avant de confirmer.",
        "Activer ce programme autorise l’envoi de son SMS en retard lorsque la programmation est activée.",
        "Activer ce SMS programmé", "Confirmer les SMS programmés", "En pause — vérification requise", "Vérifier et activer",
        "Les SMS en attente restaurés restent en pause jusqu’à ce que vous vérifiiez et activiez chacun d’eux. Restaurer les contacts, le calendrier ou les notes ne modifie pas les SMS programmés actuels."),
    "es": (
        "Revise el texto exacto del SMS para cada destinatario antes de confirmar.",
        "Activar este plan permite enviar su SMS atrasado mientras la programación esté activada.",
        "Activar este plan de SMS", "Confirmar planes de SMS", "En pausa — requiere revisión", "Revisar y activar",
        "Los planes pendientes restaurados permanecen en pausa hasta que revise y active cada uno. Restaurar contactos, calendario o notas no cambia los planes de SMS actuales."),
    "it": (
        "Controlla il testo esatto dell’SMS per ogni destinatario prima di confermare.",
        "Attivando questo piano, il suo SMS in ritardo potrà essere inviato mentre la pianificazione è attiva.",
        "Attiva questo piano SMS", "Conferma i piani SMS", "In pausa — verifica richiesta", "Verifica e attiva",
        "I piani in attesa ripristinati restano in pausa finché non verifichi e attivi ciascun piano. Il ripristino di contatti, calendario o note non modifica i piani SMS attuali."),
    "nl": (
        "Controleer vóór bevestiging de exacte sms-tekst voor elke ontvanger.",
        "Als u dit plan inschakelt, kan de achterstallige sms worden verzonden terwijl sms-planning is ingeschakeld.",
        "Dit sms-plan inschakelen", "Sms-plannen bevestigen", "Gepauzeerd — controle vereist", "Controleren en inschakelen",
        "Herstelde wachtende plannen blijven gepauzeerd totdat u elk plan controleert en inschakelt. Het herstellen van contacten, agenda of notities verandert de huidige sms-plannen niet."),
    "pt": (
        "Reveja o texto exato do SMS para cada destinatário antes de confirmar.",
        "Ativar este plano permite enviar o seu SMS em atraso enquanto o agendamento estiver ativado.",
        "Ativar este plano de SMS", "Confirmar planos de SMS", "Em pausa — revisão necessária", "Rever e ativar",
        "Os planos pendentes restaurados ficam em pausa até rever e ativar cada plano. Restaurar contactos, calendário ou notas não altera os planos de SMS atuais."),
    "ru": (
        "Перед подтверждением проверьте точный текст SMS для каждого получателя.",
        "Включение этого плана разрешает отправку его просроченного SMS, когда планирование включено.",
        "Включить этот план SMS", "Подтвердить планы SMS", "Приостановлено — требуется проверка", "Проверить и включить",
        "Восстановленные ожидающие планы остаются приостановленными, пока вы не проверите и не включите каждый план. Восстановление контактов, календаря или заметок не меняет текущие планы SMS."),
    "cs": (
        "Před potvrzením zkontrolujte přesný text SMS pro každého příjemce.",
        "Povolením tohoto plánu umožníte odeslání jeho zpožděné SMS, když je plánování zapnuté.",
        "Povolit tento plán SMS", "Potvrdit plány SMS", "Pozastaveno — vyžaduje kontrolu", "Zkontrolovat a povolit",
        "Obnovené čekající plány zůstanou pozastavené, dokud každý plán nezkontrolujete a nepovolíte. Obnovení kontaktů, kalendáře nebo poznámek nemění aktuální plány SMS."),
    "pl": (
        "Przed potwierdzeniem sprawdź dokładny tekst SMS-a dla każdego odbiorcy.",
        "Włączenie tego planu pozwala wysłać jego zaległy SMS, gdy planowanie jest włączone.",
        "Włącz ten plan SMS", "Potwierdź plany SMS", "Wstrzymano — wymagana weryfikacja", "Sprawdź i włącz",
        "Przywrócone oczekujące plany pozostają wstrzymane, dopóki nie sprawdzisz i nie włączysz każdego planu. Przywracanie kontaktów, kalendarza lub notatek nie zmienia bieżących planów SMS."),
    "hsb": (
        "Před wobkrućenjom přepruwće dokładny tekst SMS za kóždeho přijimarja.",
        "Aktiwizowanje tutoho plana dowola jeho zapózdźenu SMS pósłać, hdyž je planowanje zapinjene.",
        "Tutón SMS-plan aktiwizować", "SMS-plany wobkrućić", "Zastajene — přepruwowanje trěbne", "Přepruwować a aktiwizować",
        "Wobnowjene čakace plany wostanu zastajene, doniž kóždy plan njepřepruwujeće a njeaktiwizujeće. Wobnowjenje kontaktow, kalendra abo noticow aktualne SMS-plany njezměni."),
    "da": (
        "Kontrollér den nøjagtige SMS-tekst for hver modtager, før du bekræfter.",
        "Aktivering af denne plan tillader afsendelse af dens forsinkede SMS, når planlægning er slået til.",
        "Aktivér denne SMS-plan", "Bekræft SMS-planer", "Sat på pause — kræver kontrol", "Kontrollér og aktivér",
        "Gendannede ventende planer forbliver på pause, indtil du kontrollerer og aktiverer hver plan. Gendannelse af kontakter, kalender eller noter ændrer ikke de aktuelle SMS-planer."),
    "nb": (
        "Kontroller den nøyaktige SMS-teksten for hver mottaker før du bekrefter.",
        "Når du aktiverer denne planen, kan den forsinkede SMS-en sendes mens planlegging er slått på.",
        "Aktiver denne SMS-planen", "Bekreft SMS-planer", "Satt på pause — krever gjennomgang", "Kontroller og aktiver",
        "Gjenopprettede ventende planer forblir satt på pause til du kontrollerer og aktiverer hver plan. Gjenoppretting av kontakter, kalender eller notater endrer ikke gjeldende SMS-planer."),
    "hi": (
        "पुष्टि करने से पहले हर प्राप्तकर्ता के लिए SMS का सटीक पाठ जाँचें।",
        "इस योजना को चालू करने पर, शेड्यूलिंग चालू रहने के दौरान इसका विलंबित SMS भेजा जा सकता है।",
        "यह SMS योजना चालू करें", "SMS योजनाओं की पुष्टि करें", "रुका हुआ — समीक्षा ज़रूरी है", "जाँचें और चालू करें",
        "बहाल की गई लंबित योजनाएँ तब तक रुकी रहती हैं जब तक आप हर योजना की समीक्षा करके उसे चालू नहीं करते। संपर्क, कैलेंडर या नोट बहाल करने से वर्तमान SMS योजनाएँ नहीं बदलतीं।"),
    "zh_CN": (
        "确认前，请检查每位收件人的确切短信文本。",
        "启用此计划后，在短信定时功能开启时，其已过期的短信也可发送。",
        "启用此短信计划", "确认短信计划", "已暂停 — 需要审核", "审核并启用",
        "恢复的待发送计划将保持暂停，直到您逐个审核并启用。恢复联系人、日历或笔记不会改变当前的短信计划。"),
    "ja": (
        "確定する前に、各宛先に送信される正確な SMS 本文を確認してください。",
        "この予約を有効にすると、予約機能がオンの間は送信時刻を過ぎた SMS も送信できます。",
        "この SMS 予約を有効にする", "SMS 予約を確定", "一時停止中 — 確認が必要", "確認して有効にする",
        "復元された送信待ちの予約は、個別に確認して有効にするまで一時停止のままです。連絡先、カレンダー、メモを復元しても現在の SMS 予約は変わりません。"),
    "ar": (
        "راجع نص الرسالة القصيرة الدقيق لكل مستلم قبل التأكيد.",
        "يسمح تفعيل هذه الخطة بإرسال رسالتها المتأخرة ما دامت الجدولة مفعّلة.",
        "تفعيل خطة الرسالة هذه", "تأكيد خطط الرسائل", "متوقفة مؤقتًا — المراجعة مطلوبة", "مراجعة وتفعيل",
        "تبقى الخطط المعلّقة المستعادة متوقفة مؤقتًا حتى تراجع كل خطة وتفعّلها. لا تغيّر استعادة جهات الاتصال أو التقويم أو الملاحظات خطط الرسائل الحالية."),
    "uk": (
        "Перед підтвердженням перевірте точний текст SMS для кожного одержувача.",
        "Увімкнення цього плану дозволяє надіслати його прострочене SMS, коли планування ввімкнено.",
        "Увімкнути цей план SMS", "Підтвердити плани SMS", "Призупинено — потрібна перевірка", "Перевірити й увімкнути",
        "Відновлені плани, що очікують, залишаються призупиненими, доки ви не перевірите й не ввімкнете кожен план. Відновлення контактів, календаря чи нотаток не змінює поточні плани SMS."),
    "be": (
        "Перад пацвярджэннем праверце дакладны тэкст SMS для кожнага атрымальніка.",
        "Уключэнне гэтага плана дазваляе адправіць яго пратэрмінаванае SMS, калі планаванне ўключана.",
        "Уключыць гэты план SMS", "Пацвердзіць планы SMS", "Прыпынена — патрэбна праверка", "Праверыць і ўключыць",
        "Адноўленыя планы ў чаканні застаюцца прыпыненымі, пакуль вы не праверыце і не ўключыце кожны план. Аднаўленне кантактаў, календара або нататак не змяняе бягучыя планы SMS."),
    "tr": (
        "Onaylamadan önce her alıcı için tam SMS metnini inceleyin.",
        "Bu planı etkinleştirmek, zamanlama açıkken gecikmiş SMS’inin gönderilmesine izin verir.",
        "Bu SMS planını etkinleştir", "SMS planlarını onayla", "Duraklatıldı — inceleme gerekli", "İncele ve etkinleştir",
        "Geri yüklenen bekleyen planlar, her planı inceleyip etkinleştirene kadar duraklatılmış kalır. Kişileri, takvimi veya notları geri yüklemek mevcut SMS planlarını değiştirmez."),
}


def main():
    check = "--check" in sys.argv
    assert len(TEXT) == 20 and all(len(row) == 7 for row in TEXT.values())
    spec = importlib.util.spec_from_file_location("catalog", ROOT / "magnolie-organizer/werkzeuge/desktop_pot_merge.py")
    parser = importlib.util.module_from_spec(spec); spec.loader.exec_module(parser)
    native_path = ROOT / "magnolie-organizer-windows/app/native-i18n.json"
    native = json.loads(native_path.read_text())
    for base in (ROOT / "magnolie-organizer", ROOT / "magnolie-organizer-windows/app"):
        for po in [*sorted((base / "po").glob("*.po")), base / "po/magnolie-organizer.pot"]:
            old = po.read_text(); entries = {e["msgid"]: e for e in parser.catalog(po) if not e["obsolete"]}
            values = TEXT[po.stem] if po.suffix == ".po" else ("",) * 7
            for key, value in zip(TEXT["en"], values):
                if key in entries: assert entries[key].get("msgstr") == value, (po, key)
                else:
                    assert not check, ("missing translation", po, key)
                    old += '\n#. ASR SMS contract; manually translated.\nmsgid ' + json.dumps(key, ensure_ascii=False) + '\nmsgstr ' + json.dumps(value, ensure_ascii=False) + '\n'
            if not check and old != po.read_text(): po.write_text(old)
            if po.suffix == ".po" and base.name == "magnolie-organizer":
                mo = base / "locale" / po.stem / "LC_MESSAGES/magnolie-organizer.mo"
                assert mo.parent.is_dir(), mo.parent
                if not check: subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(mo), str(po)], check=True)
                with mo.open("rb") as stream: compiled = gettext.GNUTranslations(stream)
                for key, value in zip(TEXT["en"], values): assert compiled.gettext(key) == value, (mo, key)
        for locale, values in TEXT.items():
            js = base / "web/i18n" / (locale + ".js")
            if locale == "en" and not js.exists(): continue
            old = js.read_text()
            match = re.fullmatch(r'(window\.MagnolieI18n\.registerCatalog\("[^"]+", )(.*)(\);\s*)', old, re.S)
            assert match, js
            data = json.loads(match[2])
            for key, value in zip(TEXT["en"], values):
                if check: assert data["messages"].get(key) == value, (js, key)
                else: data["messages"][key] = value
            if not check: js.write_text(match[1] + json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + match[3])
    for locale, values in TEXT.items():
        if locale == "en": continue
        for key, value in zip(TEXT["en"], values):
            if check: assert native["locales"][locale].get(key) == value, ("native", locale, key)
            else: native["locales"][locale][key] = value
    if not check: native_path.write_text(json.dumps(native, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    print("PASS ASR SMS: 7 manually authored strings × 20 languages; both desktop PO/POT/JS, Linux MO and Windows native catalogs")


if __name__ == "__main__": main()
