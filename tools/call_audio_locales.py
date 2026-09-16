#!/usr/bin/env python3
"""Merge only the manually translated native call-audio messages."""
import json
import re
import importlib.util

import callstate_locales as catalogs

KEYS = (
    "Prefer PC speakers and microphone for calls on my own Bluetooth phone",
    "Automatic call audio is unavailable. Keep the call on the phone or select native audio manually in system settings.",
    "Automatic call audio is unsupported in this Windows build. Package identity and an approved phoneLineTransportManagement capability are required. Select native audio manually in system settings.",
)
TRANSLATIONS = {
    "en": KEYS,
    "de": (
        "Für Anrufe auf meinem eigenen Bluetooth-Telefon PC-Lautsprecher und Mikrofon bevorzugen",
        "Automatische Anruf-Audioausgabe nicht verfügbar. Lassen Sie den Anruf auf dem Telefon oder wählen Sie die native Audioausgabe manuell in den Systemeinstellungen.",
        "Diese Windows-Ausgabe unterstützt keine automatische Anruf-Audioausgabe. Erforderlich sind eine Paketidentität und eine genehmigte phoneLineTransportManagement-Berechtigung. Wählen Sie die native Audioausgabe manuell in den Systemeinstellungen."),
    "fr": (
        "Préférer les haut-parleurs et le microphone du PC pour les appels sur mon propre téléphone Bluetooth",
        "Le routage audio automatique des appels est indisponible. Gardez l’appel sur le téléphone ou sélectionnez manuellement l’audio natif dans les paramètres système.",
        "Cette version Windows ne prend pas en charge le routage audio automatique des appels. Une identité de package et la capacité phoneLineTransportManagement approuvée sont requises. Sélectionnez manuellement l’audio natif dans les paramètres système."),
    "es": (
        "Preferir los altavoces y el micrófono del PC para las llamadas de mi propio teléfono Bluetooth",
        "El audio automático de llamadas no está disponible. Mantenga la llamada en el teléfono o seleccione manualmente el audio nativo en los ajustes del sistema.",
        "Esta versión de Windows no admite el audio automático de llamadas. Se requieren una identidad de paquete y la capacidad phoneLineTransportManagement aprobada. Seleccione manualmente el audio nativo en los ajustes del sistema."),
    "it": (
        "Preferisci altoparlanti e microfono del PC per le chiamate sul mio telefono Bluetooth personale",
        "L’audio automatico delle chiamate non è disponibile. Mantieni la chiamata sul telefono o seleziona manualmente l’audio nativo nelle impostazioni di sistema.",
        "Questa versione Windows non supporta l’audio automatico delle chiamate. Sono necessarie un’identità del pacchetto e la funzionalità phoneLineTransportManagement approvata. Seleziona manualmente l’audio nativo nelle impostazioni di sistema."),
    "nl": (
        "Voorkeur voor pc-luidsprekers en microfoon bij gesprekken op mijn eigen Bluetooth-telefoon",
        "Automatische gespreksaudio is niet beschikbaar. Laat het gesprek op de telefoon of kies handmatig de systeemaudio in de systeeminstellingen.",
        "Deze Windows-versie ondersteunt geen automatische gespreksaudio. Een pakketidentiteit en goedgekeurde phoneLineTransportManagement-machtiging zijn vereist. Kies handmatig de systeemaudio in de systeeminstellingen."),
    "pt": (
        "Preferir os altifalantes e o microfone do PC nas chamadas do meu próprio telefone Bluetooth",
        "O áudio automático de chamadas não está disponível. Mantenha a chamada no telefone ou selecione manualmente o áudio nativo nas definições do sistema.",
        "Esta versão Windows não suporta áudio automático de chamadas. São necessárias uma identidade de pacote e a capacidade phoneLineTransportManagement aprovada. Selecione manualmente o áudio nativo nas definições do sistema."),
    "ru": (
        "Предпочитать динамики и микрофон ПК для звонков на моём собственном Bluetooth-телефоне",
        "Автоматическая передача звука звонка недоступна. Оставьте звонок на телефоне или выберите системный звук вручную в настройках системы.",
        "Эта сборка Windows не поддерживает автоматическую передачу звука звонка. Требуются идентификатор пакета и одобренная возможность phoneLineTransportManagement. Выберите системный звук вручную в настройках системы."),
    "cs": (
        "Upřednostnit reproduktory a mikrofon počítače pro hovory na mém vlastním telefonu Bluetooth",
        "Automatické směrování zvuku hovoru není dostupné. Ponechte hovor na telefonu nebo ručně vyberte nativní zvuk v nastavení systému.",
        "Toto sestavení pro Windows nepodporuje automatické směrování zvuku hovoru. Je vyžadována identita balíčku a schválená funkce phoneLineTransportManagement. Ručně vyberte nativní zvuk v nastavení systému."),
    "pl": (
        "Preferuj głośniki i mikrofon komputera podczas rozmów na moim własnym telefonie Bluetooth",
        "Automatyczne przekierowanie dźwięku rozmów jest niedostępne. Pozostaw rozmowę na telefonie lub ręcznie wybierz dźwięk systemowy w ustawieniach systemu.",
        "Ta wersja dla Windows nie obsługuje automatycznego przekierowania dźwięku rozmów. Wymagane są tożsamość pakietu i zatwierdzona funkcja phoneLineTransportManagement. Ręcznie wybierz dźwięk systemowy w ustawieniach systemu."),
    "hsb": (
        "Wótřečaki a mikrofon PC za zawołanja na mojim swójskim Bluetooth-telefonje preferować",
        "Awtomatiske přenošowanje zuka zawołanja k dispoziciji njeje. Wostajće zawołanje na telefonje abo wubjerće natiwny zuk manuelnje w systemowych nastajenjach.",
        "Tute Windows-wudaće awtomatiske přenošowanje zuka zawołanja njepodpěruje. Identita pakćika a schwaleny přistup phoneLineTransportManagement stej trěbnej. Wubjerće natiwny zuk manuelnje w systemowych nastajenjach."),
    "da": (
        "Foretræk pc-højttalere og mikrofon til opkald på min egen Bluetooth-telefon",
        "Automatisk opkaldslyd er ikke tilgængelig. Behold opkaldet på telefonen, eller vælg systemets lyd manuelt i systemindstillingerne.",
        "Denne Windows-udgave understøtter ikke automatisk opkaldslyd. Pakkeidentitet og en godkendt phoneLineTransportManagement-funktion er påkrævet. Vælg systemets lyd manuelt i systemindstillingerne."),
    "nb": (
        "Foretrekk PC-høyttalere og mikrofon for samtaler på min egen Bluetooth-telefon",
        "Automatisk samtalelyd er utilgjengelig. Behold samtalen på telefonen, eller velg systemlyd manuelt i systeminnstillingene.",
        "Denne Windows-utgaven støtter ikke automatisk samtalelyd. Pakkeidentitet og en godkjent phoneLineTransportManagement-funksjon kreves. Velg systemlyd manuelt i systeminnstillingene."),
    "hi": (
        "मेरे अपने Bluetooth फ़ोन की कॉल के लिए PC के स्पीकर और माइक्रोफ़ोन को प्राथमिकता दें",
        "कॉल का ऑडियो अपने-आप भेजना उपलब्ध नहीं है। कॉल फ़ोन पर रखें या सिस्टम सेटिंग में मूल ऑडियो विकल्प स्वयं चुनें।",
        "इस Windows संस्करण में कॉल का ऑडियो अपने-आप भेजना समर्थित नहीं है। पैकेज पहचान और स्वीकृत phoneLineTransportManagement क्षमता आवश्यक हैं। सिस्टम सेटिंग में मूल ऑडियो विकल्प स्वयं चुनें।"),
    "zh_CN": (
        "优先使用电脑扬声器和麦克风接听我自己的 Bluetooth 手机上的通话",
        "自动通话音频不可用。请在手机上继续通话，或在系统设置中手动选择原生音频。",
        "此 Windows 版本不支持自动通话音频。需要软件包标识和已获批准的 phoneLineTransportManagement 功能。请在系统设置中手动选择原生音频。"),
    "ja": (
        "自分の Bluetooth 電話での通話には PC のスピーカーとマイクを優先する",
        "自動通話音声は利用できません。電話で通話を続けるか、システム設定でネイティブ音声を手動で選択してください。",
        "この Windows ビルドでは自動通話音声はサポートされていません。パッケージ ID と承認済みの phoneLineTransportManagement 機能が必要です。システム設定でネイティブ音声を手動で選択してください。"),
    "ar": (
        "تفضيل مكبرات صوت الكمبيوتر وميكروفونه للمكالمات على هاتفي الشخصي المتصل عبر Bluetooth",
        "صوت المكالمات التلقائي غير متاح. أبقِ المكالمة على الهاتف أو اختر الصوت الأصلي يدويًا في إعدادات النظام.",
        "لا يدعم إصدار Windows هذا صوت المكالمات التلقائي. يلزم توفر هوية حزمة وإمكانية phoneLineTransportManagement معتمدة. اختر الصوت الأصلي يدويًا في إعدادات النظام."),
    "uk": (
        "Надавати перевагу динамікам і мікрофону ПК для дзвінків на моєму власному Bluetooth-телефоні",
        "Автоматичне передавання звуку дзвінка недоступне. Залиште дзвінок на телефоні або виберіть системний звук вручну в налаштуваннях системи.",
        "Ця збірка Windows не підтримує автоматичне передавання звуку дзвінка. Потрібні ідентифікатор пакета та схвалена можливість phoneLineTransportManagement. Виберіть системний звук вручну в налаштуваннях системи."),
    "be": (
        "Аддаваць перавагу дынамікам і мікрафону ПК для званкоў на маім уласным Bluetooth-тэлефоне",
        "Аўтаматычная перадача гуку званка недаступная. Пакіньце званок на тэлефоне або выберыце сістэмны гук уручную ў наладах сістэмы.",
        "Гэтая зборка Windows не падтрымлівае аўтаматычную перадачу гуку званка. Патрэбныя ідэнтыфікатар пакета і ўхваленая магчымасць phoneLineTransportManagement. Выберыце сістэмны гук уручную ў наладах сістэмы."),
    "tr": (
        "Kendi Bluetooth telefonumdaki aramalar için PC hoparlörlerini ve mikrofonunu tercih et",
        "Otomatik arama sesi kullanılamıyor. Aramayı telefonda tutun veya sistem ayarlarından yerel sesi elle seçin.",
        "Bu Windows derlemesi otomatik arama sesini desteklemiyor. Paket kimliği ve onaylanmış phoneLineTransportManagement yeteneği gerekiyor. Sistem ayarlarından yerel sesi elle seçin."),
}


def main():
    spec = importlib.util.spec_from_file_location("audio_catalog", catalogs.ROOT / "magnolie-organizer-2.0.0/werkzeuge/desktop_pot_merge.py")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    reused = "Bluetooth device for call audio"
    translations = {}
    for locale, values in TRANSLATIONS.items():
        existing = ({entry["msgid"]: entry.get("msgstr") for entry in parser.catalog(
            catalogs.ROOT / "magnolie-organizer-2.0.0/po" / (locale + ".po")) if not entry["obsolete"]}
            if locale != "en" else {reused: reused})
        translations[locale] = (*values, existing[reused])
    keys = (*KEYS, reused)
    catalogs.KEYS, catalogs.TRANSLATIONS = keys, translations
    catalogs.main()
    for directory in (catalogs.ROOT / "magnolie-organizer-2.0.0/web/i18n",
                      catalogs.ROOT / "Magnolie-Organizer-Windows-2.0.0/app/web/i18n"):
        for locale, values in translations.items():
            if locale == "en":
                continue
            path = directory / (locale + ".js")
            text = path.read_text(encoding="utf-8")
            match = re.fullmatch(r'(window\.MagnolieI18n\.registerCatalog\("[^"\n]+", )(.*)(\);\s*)', text)
            assert match, path
            catalog = json.loads(match[2])
            for key, value in zip(keys, values):
                assert key not in catalog["messages"] or catalog["messages"][key] == value
                catalog["messages"][key] = value
            path.write_text(match[1] + json.dumps(catalog, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) + match[3], encoding="utf-8")


if __name__ == "__main__":
    main()
