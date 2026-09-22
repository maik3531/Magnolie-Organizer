#!/usr/bin/env python3
"""Vereinigt bestehende PO- und generierte Kataloge deterministisch mit einem POT."""

import gettext
import json
import os
import re
import subprocess
import sys
import tempfile

ERGÄNZUNGEN = {
    "Google requires browser sign-in. Google synchronization is not yet available in this Windows version; a DAV password cannot enable it.": {
        "de": "Google benötigt eine Anmeldung im Browser. Der Google-Abgleich ist in dieser Windows-Version noch nicht verfügbar; ein DAV-Kennwort kann ihn nicht aktivieren.",
        "fr": "Google exige une connexion dans le navigateur. La synchronisation Google n’est pas encore disponible dans cette version Windows ; un mot de passe DAV ne peut pas l’activer.",
        "es": "Google requiere iniciar sesión en el navegador. La sincronización con Google aún no está disponible en esta versión de Windows; una contraseña DAV no puede activarla.",
        "it": "Google richiede l’accesso nel browser. La sincronizzazione Google non è ancora disponibile in questa versione Windows; una password DAV non può attivarla.",
        "nl": "Google vereist aanmelding in de browser. Google-synchronisatie is nog niet beschikbaar in deze Windows-versie; een DAV-wachtwoord kan deze niet inschakelen.",
        "pt": "O Google requer início de sessão no navegador. A sincronização com o Google ainda não está disponível nesta versão Windows; uma palavra-passe DAV não a pode ativar.",
        "ru": "Google требует входа через браузер. Синхронизация с Google пока недоступна в этой версии для Windows; пароль DAV не может её включить.",
        "cs": "Google vyžaduje přihlášení v prohlížeči. Synchronizace s Googlem v této verzi pro Windows zatím není dostupná; heslo DAV ji nemůže zapnout.",
        "pl": "Google wymaga logowania w przeglądarce. Synchronizacja z Google nie jest jeszcze dostępna w tej wersji dla Windows; hasło DAV nie może jej włączyć.",
        "hsb": "Google sej přizjewjenje we wobhladowaku žada. Synchronizacija z Google w tutej Windows-wersiji hišće k dispoziciji njeje; hesło DAV ju njemóže zmóžnić.",
        "da": "Google kræver login i browseren. Google-synkronisering er endnu ikke tilgængelig i denne Windows-version; en DAV-adgangskode kan ikke aktivere den.",
        "nb": "Google krever innlogging i nettleseren. Google-synkronisering er ennå ikke tilgjengelig i denne Windows-versjonen; et DAV-passord kan ikke aktivere den.",
        "hi": "Google के लिए ब्राउज़र में साइन इन करना आवश्यक है। इस Windows संस्करण में Google सिंक्रनाइज़ेशन अभी उपलब्ध नहीं है; DAV पासवर्ड इसे सक्षम नहीं कर सकता।",
        "zh_CN": "Google 需要在浏览器中登录。此 Windows 版本尚不支持 Google 同步；DAV 密码无法启用此功能。",
        "ja": "Google にはブラウザーでのログインが必要です。この Windows 版では Google 同期はまだ利用できません。DAV パスワードでは有効にできません。",
        "ar": "يتطلب Google تسجيل الدخول في المتصفح. مزامنة Google غير متاحة بعد في إصدار Windows هذا؛ لا يمكن تفعيلها بكلمة مرور DAV.",
        "uk": "Google потребує входу через браузер. Синхронізація з Google поки недоступна в цій версії для Windows; пароль DAV не може її ввімкнути.",
        "be": "Google патрабуе ўваходу праз браўзер. Сінхранізацыя з Google пакуль недаступная ў гэтай версіі для Windows; пароль DAV не можа яе ўключыць.",
        "tr": "Google, tarayıcıda oturum açılmasını gerektirir. Bu Windows sürümünde Google eşitlemesi henüz kullanılamıyor; DAV parolası bunu etkinleştiremez.",
    },
    "Sign-in failed. Check the account and authentication method required by your provider.": {
        "de": "Anmeldung fehlgeschlagen. Prüfen Sie das Konto und das vom Anbieter verlangte Anmeldeverfahren.",
        "fr": "Échec de la connexion. Vérifiez le compte et la méthode d’authentification exigée par votre fournisseur.",
        "es": "No se pudo iniciar sesión. Compruebe la cuenta y el método de autenticación requerido por su proveedor.",
        "it": "Accesso non riuscito. Controllare l’account e il metodo di autenticazione richiesto dal fornitore.",
        "nl": "Aanmelden mislukt. Controleer het account en de vereiste aanmeldmethode van uw aanbieder.",
        "pt": "Falha ao iniciar sessão. Verifique a conta e o método de autenticação exigido pelo fornecedor.",
        "ru": "Не удалось войти. Проверьте учётную запись и требуемый поставщиком способ аутентификации.",
        "cs": "Přihlášení se nezdařilo. Zkontrolujte účet a způsob ověření požadovaný poskytovatelem.",
        "pl": "Logowanie nie powiodło się. Sprawdź konto i metodę uwierzytelniania wymaganą przez dostawcę.",
        "hsb": "Přizjewjenje je so njeporadźiło. Přepruwujće konto a wot poskićowarja požadane přizjewjenske jednanje.",
        "da": "Login mislykkedes. Kontrollér kontoen og den godkendelsesmetode, som din udbyder kræver.",
        "nb": "Innlogging mislyktes. Kontroller kontoen og autentiseringsmetoden leverandøren krever.",
        "hi": "साइन इन विफल रहा। खाते और प्रदाता द्वारा आवश्यक प्रमाणीकरण विधि की जाँच करें।",
        "zh_CN": "登录失败。请检查账户及提供商要求的身份验证方式。",
        "ja": "ログインに失敗しました。アカウントとプロバイダーが要求する認証方法を確認してください。",
        "ar": "فشل تسجيل الدخول. تحقق من الحساب وطريقة المصادقة التي يتطلبها مزود الخدمة.",
        "uk": "Не вдалося ввійти. Перевірте обліковий запис і спосіб автентифікації, якого вимагає постачальник.",
        "be": "Не ўдалося ўвайсці. Праверце ўліковы запіс і спосаб аўтэнтыфікацыі, які патрабуе пастаўшчык.",
        "tr": "Oturum açılamadı. Hesabı ve sağlayıcınızın gerektirdiği kimlik doğrulama yöntemini kontrol edin.",
    },
    "The server denied access. Check this account's permissions.": {
        "de": "Der Server hat den Zugriff verweigert. Prüfen Sie die Berechtigungen dieses Kontos.",
        "fr": "Le serveur a refusé l’accès. Vérifiez les autorisations de ce compte.",
        "es": "El servidor denegó el acceso. Compruebe los permisos de esta cuenta.",
        "it": "Il server ha negato l’accesso. Controllare i permessi di questo account.",
        "nl": "De server heeft toegang geweigerd. Controleer de machtigingen van dit account.",
        "pt": "O servidor recusou o acesso. Verifique as permissões desta conta.",
        "ru": "Сервер отказал в доступе. Проверьте разрешения этой учётной записи.",
        "cs": "Server odepřel přístup. Zkontrolujte oprávnění tohoto účtu.",
        "pl": "Serwer odmówił dostępu. Sprawdź uprawnienia tego konta.",
        "hsb": "Serwer je přistup wotpokazał. Přepruwujće prawa tutoho konta.",
        "da": "Serveren nægtede adgang. Kontrollér denne kontos tilladelser.",
        "nb": "Serveren nektet tilgang. Kontroller tillatelsene til denne kontoen.",
        "hi": "सर्वर ने पहुँच अस्वीकार कर दी। इस खाते की अनुमतियाँ जाँचें।",
        "zh_CN": "服务器拒绝访问。请检查此账户的权限。",
        "ja": "サーバーがアクセスを拒否しました。このアカウントの権限を確認してください。",
        "ar": "رفض الخادم الوصول. تحقق من أذونات هذا الحساب.",
        "uk": "Сервер відмовив у доступі. Перевірте дозволи цього облікового запису.",
        "be": "Сервер адмовіў у доступе. Праверце дазволы гэтага ўліковага запісу.",
        "tr": "Sunucu erişimi reddetti. Bu hesabın izinlerini kontrol edin.",
    },
    "Are you really sure?": {
        "ar": "هل أنت متأكد حقًا؟", "be": "Вы сапраўды ўпэўнены?",
        "cs": "Opravdu jste si jisti?", "da": "Er du helt sikker?",
        "de": "Sind Sie wirklich sicher?", "es": "¿Está realmente seguro?",
        "fr": "Êtes-vous vraiment sûr ?", "hi": "क्या आप वाकई सुनिश्चित हैं?",
        "hsb": "Sće woprawdźe wěsty?", "it": "È davvero sicuro?",
        "ja": "本当によろしいですか？", "nb": "Er du helt sikker?",
        "nl": "Weet u het echt zeker?", "pl": "Czy na pewno?",
        "pt": "Tem mesmo a certeza?", "ru": "Вы действительно уверены?",
        "tr": "Gerçekten emin misiniz?", "uk": "Ви справді впевнені?",
        "zh_CN": "您真的确定吗？",
    },
    "Deleted and missing data is restored; newer existing data is retained.": {
        "fr": "Les données supprimées et manquantes sont restaurées ; les données existantes plus récentes sont conservées.",
        "es": "Se restauran los datos eliminados y faltantes; se conservan los datos existentes más recientes.",
        "it": "I dati eliminati e mancanti vengono ripristinati; i dati esistenti più recenti vengono conservati.",
        "nl": "Verwijderde en ontbrekende gegevens worden hersteld; nieuwere bestaande gegevens blijven behouden.",
        "pt": "Os dados eliminados e em falta são restaurados; os dados existentes mais recentes são mantidos.",
        "ru": "Удалённые и отсутствующие данные восстанавливаются; более новые существующие данные сохраняются.",
        "cs": "Odstraněná a chybějící data se obnoví; novější existující data zůstanou zachována.",
        "pl": "Usunięte i brakujące dane zostaną przywrócone; nowsze istniejące dane zostaną zachowane.",
        "hsb": "Zhašane a falowace daty so wobnowja; nowše eksistowace daty so wobchowaja.",
        "da": "Slettede og manglende data gendannes; nyere eksisterende data bevares.",
        "nb": "Slettede og manglende data gjenopprettes; nyere eksisterende data beholdes.",
        "hi": "हटाया गया और अनुपलब्ध डेटा पुनर्स्थापित किया जाता है; नया मौजूदा डेटा रखा जाता है।",
        "zh_CN": "恢复已删除和缺失的数据；保留较新的现有数据。",
        "ja": "削除されたデータと不足しているデータを復元し、既存の新しいデータは保持します。",
        "ar": "تُستعاد البيانات المحذوفة والمفقودة، وتُحتفظ بالبيانات الموجودة الأحدث.",
        "uk": "Видалені та відсутні дані відновлюються; новіші наявні дані зберігаються.",
        "be": "Выдаленыя і адсутныя даныя аднаўляюцца; навейшыя існыя даныя захоўваюцца.",
        "tr": "Silinen ve eksik veriler geri yüklenir; daha yeni mevcut veriler korunur.",
    },
    "The selected areas are reset exactly; data added later is removed.": {
        "fr": "Les zones sélectionnées sont réinitialisées exactement ; les données ajoutées ultérieurement sont supprimées.",
        "es": "Las áreas seleccionadas se restablecen exactamente; se eliminan los datos añadidos posteriormente.",
        "it": "Le aree selezionate vengono ripristinate esattamente; i dati aggiunti in seguito vengono rimossi.",
        "nl": "De geselecteerde gebieden worden exact teruggezet; later toegevoegde gegevens worden verwijderd.",
        "pt": "As áreas selecionadas são repostas exatamente; os dados adicionados posteriormente são removidos.",
        "ru": "Выбранные области точно возвращаются к прежнему состоянию; добавленные позже данные удаляются.",
        "cs": "Vybrané oblasti se přesně vrátí do dřívějšího stavu; později přidaná data se odstraní.",
        "pl": "Wybrane obszary zostaną dokładnie przywrócone; dane dodane później zostaną usunięte.",
        "hsb": "Wubrane wobłuki so eksaktnje wróćo stajeja; pozdźišo přidate daty so wotstronja.",
        "da": "De valgte områder nulstilles nøjagtigt; data, der er tilføjet senere, fjernes.",
        "nb": "De valgte områdene tilbakestilles nøyaktig; data som ble lagt til senere, fjernes.",
        "hi": "चुने गए क्षेत्रों को ठीक पुराने रूप में लौटाया जाता है; बाद में जोड़ा गया डेटा हटा दिया जाता है।",
        "zh_CN": "所选区域将精确重置；之后添加的数据将被移除。",
        "ja": "選択した領域を以前の状態に正確に戻し、その後に追加されたデータを削除します。",
        "ar": "تُعاد المناطق المحددة بدقة إلى حالتها السابقة، وتُحذف البيانات المضافة لاحقًا.",
        "uk": "Вибрані області точно повертаються до попереднього стану; додані пізніше дані видаляються.",
        "be": "Выбраныя вобласці дакладна вяртаюцца да ранейшага стану; дададзеныя пазней даныя выдаляюцца.",
        "tr": "Seçilen alanlar önceki duruma tam olarak döndürülür; daha sonra eklenen veriler kaldırılır.",
    },
    "Operating system": {
        "ar": "نظام التشغيل", "be": "Аперацыйная сістэма", "cs": "Operační systém",
        "da": "Operativsystem", "de": "Betriebssystem", "es": "Sistema operativo",
        "fr": "Système d’exploitation", "hi": "ऑपरेटिंग सिस्टम", "hsb": "Dźěłowy system",
        "it": "Sistema operativo", "ja": "オペレーティングシステム", "nb": "Operativsystem",
        "nl": "Besturingssysteem", "pl": "System operacyjny", "pt": "Sistema operativo",
        "ru": "Операционная система", "tr": "İşletim sistemi", "uk": "Операційна система",
        "zh_CN": "操作系统",
    },
}


def po_katalog(pfad):
    with tempfile.TemporaryDirectory(prefix="magnolie-po-merge-") as ordner:
        mo = os.path.join(ordner, "catalog.mo")
        subprocess.run([os.environ.get("MAGNOLIE_MSGFMT", "msgfmt"), "-o", mo, pfad],
                       check=True)
        with open(mo, "rb") as datei:
            return dict(gettext.GNUTranslations(datei)._catalog)


def js_katalog(pfad):
    text = open(pfad, encoding="utf-8").read()
    treffer = re.fullmatch(r'window\.MagnolieI18n\.registerCatalog\((".*?"),\s*(\{.*\})\);\s*',
                           text, re.DOTALL)
    if not treffer:
        raise ValueError("Ungültiger generierter Webkatalog: " + pfad)
    return json.loads(treffer.group(2))["messages"]


def feld(block, name):
    treffer = re.search(r"^" + name + r' (".*")$', block, re.MULTILINE)
    if not treffer:
        return None
    wert = json.loads(treffer.group(1))
    position = treffer.end()
    while position < len(block):
        folge = re.match(r'\n(".*")', block[position:])
        if not folge:
            break
        wert += json.loads(folge.group(1))
        position += len(folge.group(0))
    return wert


def quoted(name, wert):
    return name + " " + json.dumps(wert, ensure_ascii=False)


def haupt(argv):
    if len(argv) != 7:
        raise SystemExit("Aufruf: po_vereinigen.py VORLAGE.pot AKTUELL.po ALT.js ALT-NATIV.json SPRACHE ZIEL.po")
    vorlage, aktuell, alt, alt_nativ, sprache, ziel = argv[1:]
    aktuelle = po_katalog(aktuell)
    alte = js_katalog(alt)
    with open(alt_nativ, encoding="utf-8") as datei:
        alte.update(json.load(datei)["locales"][sprache])
    bloecke = open(vorlage, encoding="utf-8").read().split("\n\n")
    ausgabe = []
    for block in bloecke:
        msgid = feld(block, "msgid")
        if msgid is None:
            ausgabe.append(block)
            continue
        if msgid == "":
            kopf = aktuelle.get("", "")
            ausgabe.append(re.sub(r'^msgstr ""(?:\n".*")*', lambda _: quoted("msgstr", kopf),
                                  block.replace("#, fuzzy\n", ""), count=1, flags=re.MULTILINE))
            continue
        context = feld(block, "msgctxt")
        key = (context + "\x04" + msgid) if context else msgid
        plural = feld(block, "msgid_plural")
        if plural is None:
            wert = alte.get(key) or ERGÄNZUNGEN.get(key, {}).get(sprache) or aktuelle.get(key)
            if not isinstance(wert, str) or not wert:
                raise ValueError("Übersetzung fehlt: " + key)
            ersetzt = re.sub(r'^msgstr ""(?:\n".*")*', lambda _: quoted("msgstr", wert), block,
                             count=1, flags=re.MULTILINE)
        else:
            altwerte = alte.get(key, [])
            zeilen = []
            index = 0
            while (key, index) in aktuelle or index < len(altwerte):
                wert = (altwerte[index] if index < len(altwerte) else "") or aktuelle.get((key, index))
                if not wert:
                    raise ValueError("Pluralübersetzung fehlt: " + key)
                zeilen.append(quoted("msgstr[%d]" % index, wert))
                index += 1
            ersetzt = re.sub(r'^msgstr\[0\] ""(?:\nmsgstr\[\d+\] "")*', lambda _: "\n".join(zeilen),
                             block, count=1, flags=re.MULTILINE)
        ausgabe.append(ersetzt)
    with open(ziel, "w", encoding="utf-8", newline="\n") as datei:
        datei.write("\n\n".join(ausgabe).rstrip() + "\n")


if __name__ == "__main__":
    haupt(sys.argv)
