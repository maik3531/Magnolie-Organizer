#include <Akonadi/Collection>
#include <Akonadi/CollectionFetchJob>
#include <Akonadi/CollectionFetchScope>
#include <Akonadi/Item>
#include <Akonadi/ItemCreateJob>
#include <Akonadi/ItemDeleteJob>
#include <Akonadi/ItemFetchJob>
#include <Akonadi/ItemFetchScope>
#include <Akonadi/ItemModifyJob>
#include <Akonadi/ServerManager>

#include <KCalendarCore/Event>
#include <KCalendarCore/ICalFormat>
#include <KCalendarCore/Incidence>
#include <KCalendarCore/Journal>
#include <KCalendarCore/MemoryCalendar>
#include <KCalendarCore/Todo>
#include <KContacts/Addressee>
#include <KContacts/VCardConverter>

#include <QCoreApplication>
#include <QDateTime>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusReply>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QHash>
#include <QMap>
#include <QRegularExpression>
#include <QSet>
#include <QStringList>
#include <QTimeZone>

#include <cmath>
#include <cstdio>
#include <limits>
#include <memory>
#include <stdexcept>

namespace
{
constexpr qint64 MaxInput = 16 * 1024 * 1024;
constexpr qint64 MaxOutput = 64 * 1024 * 1024;
constexpr qsizetype MaxItems = 100000;
constexpr qint64 MaxExactJsonInteger = 9007199254740991LL;

class ProtocolError : public std::runtime_error
{
public:
    explicit ProtocolError(const QString &message)
        : std::runtime_error(message.toUtf8().constData())
    {
    }
};

enum class Kind { Calendar, AddressBook };

QString kindName(Kind kind)
{
    return kind == Kind::Calendar ? QStringLiteral("calendar") : QStringLiteral("addressbook");
}

Kind parseKind(const QJsonObject &object)
{
    const QJsonValue value = object.value(QStringLiteral("kind"));
    if (!value.isString()) {
        throw ProtocolError(QStringLiteral("'kind' must be a string"));
    }
    if (value.toString() == QLatin1String("calendar")) {
        return Kind::Calendar;
    }
    if (value.toString() == QLatin1String("addressbook")) {
        return Kind::AddressBook;
    }
    throw ProtocolError(QStringLiteral("'kind' must be 'calendar' or 'addressbook'"));
}

void requireKeys(const QJsonObject &object, std::initializer_list<const char *> keys)
{
    QSet<QString> expected;
    for (const char *key : keys) {
        expected.insert(QString::fromLatin1(key));
    }
    for (auto it = object.constBegin(); it != object.constEnd(); ++it) {
        if (!expected.contains(it.key())) {
            throw ProtocolError(QStringLiteral("unexpected key '%1'").arg(it.key()));
        }
    }
    for (const QString &key : expected) {
        if (!object.contains(key)) {
            throw ProtocolError(QStringLiteral("missing key '%1'").arg(key));
        }
    }
}

QString stringValue(const QJsonObject &object, const char *key, bool allowEmpty = false)
{
    const QString name = QString::fromLatin1(key);
    const QJsonValue value = object.value(name);
    if (!value.isString() || (!allowEmpty && value.toString().isEmpty())) {
        throw ProtocolError(QStringLiteral("'%1' must be a %2string").arg(name, allowEmpty ? QString() : QStringLiteral("non-empty ")));
    }
    return value.toString();
}

qint64 integerValue(const QJsonObject &object, const char *key, qint64 minimum, qint64 maximum)
{
    const QString name = QString::fromLatin1(key);
    const QJsonValue value = object.value(name);
    if (!value.isDouble()) {
        throw ProtocolError(QStringLiteral("'%1' must be a number").arg(name));
    }
    const double number = value.toDouble();
    if (!std::isfinite(number) || std::floor(number) != number || number < static_cast<double>(minimum)
        || number > static_cast<double>(maximum)) {
        throw ProtocolError(QStringLiteral("'%1' is outside its integer range").arg(name));
    }
    return static_cast<qint64>(number);
}

void verifyServerBinding(const QJsonObject &object)
{
    const qint64 generation = integerValue(object, "generation", 0, MaxExactJsonInteger);
    const QString instance = stringValue(object, "instance", true);
    if (instance != Akonadi::ServerManager::instanceIdentifier()) {
        throw ProtocolError(QStringLiteral("Akonadi instance changed; select the source again"));
    }
    // The generation cache is populated by the first server handshake, not by
    // ServerManager::generation() itself. Every protocol request is a new process.
    if (Akonadi::ServerManager::generation() == 0) {
        auto job = std::make_unique<Akonadi::CollectionFetchJob>(Akonadi::Collection::root(), Akonadi::CollectionFetchJob::FirstLevel);
        job->setAutoDelete(false);
        if (!job->exec()) {
            throw ProtocolError(QStringLiteral("Akonadi session initialization failed: %1").arg(job->errorString()));
        }
    }
    if (generation != static_cast<qint64>(Akonadi::ServerManager::generation())
        || instance != Akonadi::ServerManager::instanceIdentifier()) {
        throw ProtocolError(QStringLiteral("Akonadi instance changed; select the source again"));
    }
}

double jsonInteger(qint64 value, const QString &field)
{
    if (value < -MaxExactJsonInteger || value > MaxExactJsonInteger) {
        throw ProtocolError(QStringLiteral("'%1' cannot be represented exactly as a JSON number").arg(field));
    }
    return static_cast<double>(value);
}

template<typename Job>
void runJob(Job *job, const QString &operation)
{
    job->setAutoDelete(false);
    if (!job->exec()) {
        const QString detail = job->errorString().isEmpty() ? QStringLiteral("unknown Akonadi error") : job->errorString();
        throw ProtocolError(QStringLiteral("%1 failed: %2").arg(operation, detail));
    }
}

bool supportsKind(const Akonadi::Collection &collection, Kind kind)
{
    const QStringList types = collection.contentMimeTypes();
    if (kind == Kind::Calendar) {
        return types.contains(KCalendarCore::Event::eventMimeType()) || types.contains(QStringLiteral("text/calendar"));
    }
    return types.contains(KContacts::Addressee::mimeType())
        || types.contains(QStringLiteral("text/vcard"))
        || types.contains(QStringLiteral("text/directory"));
}

Akonadi::Collection fetchCollection(qint64 id, Kind kind)
{
    auto job = std::make_unique<Akonadi::CollectionFetchJob>(Akonadi::Collection(id), Akonadi::CollectionFetchJob::Base);
    runJob(job.get(), QStringLiteral("collection fetch"));
    if (job->collections().size() != 1) {
        throw ProtocolError(QStringLiteral("collection does not exist"));
    }
    const Akonadi::Collection collection = job->collections().constFirst();
    if (collection.isVirtual()) {
        throw ProtocolError(QStringLiteral("virtual collections are not supported"));
    }
    if (!supportsKind(collection, kind)) {
        throw ProtocolError(QStringLiteral("collection does not support kind '%1'").arg(kindName(kind)));
    }
    return collection;
}

Akonadi::Item::List fetchCollectionItems(const Akonadi::Collection &collection)
{
    auto job = std::make_unique<Akonadi::ItemFetchJob>(collection);
    job->fetchScope().fetchFullPayload();
    job->fetchScope().setAncestorRetrieval(Akonadi::ItemFetchScope::Parent);
    runJob(job.get(), QStringLiteral("full collection fetch"));
    return job->items();
}

Akonadi::Item::List fetchStableCollectionItems(const Akonadi::Collection &collection)
{
    const Akonadi::Item::List first = fetchCollectionItems(collection);
    const Akonadi::Item::List second = fetchCollectionItems(collection);
    if (first.size() > MaxItems || second.size() > MaxItems) {
        throw ProtocolError(QStringLiteral("collection contains too many items"));
    }
    auto signature = [](const Akonadi::Item::List &items) {
        QMap<qint64, int> result;
        for (const Akonadi::Item &item : items) {
            if (!item.isValid() || result.contains(item.id())) {
                throw ProtocolError(QStringLiteral("collection returned invalid or duplicate item metadata"));
            }
            result.insert(item.id(), item.revision());
        }
        return result;
    };
    if (signature(first) != signature(second)) {
        throw ProtocolError(QStringLiteral("collection changed while it was being read"));
    }
    return second;
}

Akonadi::Item fetchItem(qint64 id)
{
    auto job = std::make_unique<Akonadi::ItemFetchJob>(Akonadi::Item(id));
    job->fetchScope().fetchFullPayload();
    job->fetchScope().setAncestorRetrieval(Akonadi::ItemFetchScope::Parent);
    runJob(job.get(), QStringLiteral("full item fetch"));
    if (job->items().size() != 1) {
        throw ProtocolError(QStringLiteral("item does not exist"));
    }
    return job->items().constFirst();
}

QString itemUid(const Akonadi::Item &item, Kind kind)
{
    if (kind == Kind::Calendar) {
        if (!item.hasPayload<KCalendarCore::Incidence::Ptr>()) {
            throw ProtocolError(QStringLiteral("calendar item has no complete incidence payload"));
        }
        const KCalendarCore::Incidence::Ptr incidence = item.payload<KCalendarCore::Incidence::Ptr>();
        if (!incidence || incidence->type() != KCalendarCore::IncidenceBase::TypeEvent) {
            throw ProtocolError(QStringLiteral("calendar item is not an event"));
        }
        if (incidence->uid().isEmpty()) {
            throw ProtocolError(QStringLiteral("calendar item has no logical UID"));
        }
        return incidence->uid();
    }

    if (!item.hasPayload<KContacts::Addressee>()) {
        throw ProtocolError(QStringLiteral("address-book item has no complete contact payload"));
    }
    const KContacts::Addressee contact = item.payload<KContacts::Addressee>();
    if (contact.isEmpty() || contact.uid().isEmpty()) {
        throw ProtocolError(QStringLiteral("address-book item is empty or has no logical UID"));
    }
    return contact.uid();
}

QString serializeItem(const Akonadi::Item &item, Kind kind)
{
    if (kind == Kind::Calendar) {
        itemUid(item, kind);
        const auto calendar = KCalendarCore::MemoryCalendar::Ptr(new KCalendarCore::MemoryCalendar(QTimeZone::utc()));
        const KCalendarCore::Incidence::Ptr incidence = item.payload<KCalendarCore::Incidence::Ptr>();
        if (!calendar->addIncidence(KCalendarCore::Incidence::Ptr(incidence->clone()))) {
            throw ProtocolError(QStringLiteral("event cannot be added to a VCALENDAR"));
        }
        KCalendarCore::ICalFormat converter;
        const QString result = converter.toString(calendar.staticCast<KCalendarCore::Calendar>());
        if (result.isEmpty()) {
            throw ProtocolError(QStringLiteral("event cannot be serialized as VCALENDAR"));
        }
        return result;
    }

    itemUid(item, kind);
    KContacts::VCardConverter converter;
    const QByteArray result = converter.createVCard(item.payload<KContacts::Addressee>(), KContacts::VCardConverter::v3_0);
    if (result.isEmpty()) {
        throw ProtocolError(QStringLiteral("contact cannot be serialized as vCard 3.0"));
    }
    return QString::fromUtf8(result);
}

bool isIgnoredCalendarItem(const Akonadi::Item &item)
{
    if (item.mimeType() == KCalendarCore::Todo::todoMimeType() || item.mimeType() == KCalendarCore::Journal::journalMimeType()) {
        return true;
    }
    if (!item.hasPayload<KCalendarCore::Incidence::Ptr>()) {
        return false;
    }
    const KCalendarCore::Incidence::Ptr incidence = item.payload<KCalendarCore::Incidence::Ptr>();
    return incidence && (incidence->type() == KCalendarCore::IncidenceBase::TypeTodo
                         || incidence->type() == KCalendarCore::IncidenceBase::TypeJournal);
}

QJsonObject metadata(const Akonadi::Item &item, Kind kind, bool withContent = false)
{
    if (!item.isValid() || item.id() <= 0 || item.revision() < 0) {
        throw ProtocolError(QStringLiteral("Akonadi returned invalid item metadata"));
    }
    if (!item.modificationTime().isValid()) {
        throw ProtocolError(QStringLiteral("Akonadi returned an invalid modification time"));
    }
    QJsonObject result{
        {QStringLiteral("id"), jsonInteger(item.id(), QStringLiteral("item id"))},
        {QStringLiteral("revision"), item.revision()},
        {QStringLiteral("gid"), itemUid(item, kind)},
    };
    if (withContent) {
        result.insert(QStringLiteral("content"), serializeItem(item, kind));
    }
    return result;
}

KCalendarCore::Event::Ptr parseEvent(const QString &content)
{
    static const QRegularExpression beginCalendar(QStringLiteral("(?im)^BEGIN:VCALENDAR[\\t ]*\\r?$"));
    static const QRegularExpression endCalendar(QStringLiteral("(?im)^END:VCALENDAR[\\t ]*\\r?$"));
    static const QRegularExpression beginEvent(QStringLiteral("(?im)^BEGIN:VEVENT[\\t ]*\\r?$"));
    static const QRegularExpression endEvent(QStringLiteral("(?im)^END:VEVENT[\\t ]*\\r?$"));
    if (content.count(beginCalendar) != 1 || content.count(endCalendar) != 1 || content.count(beginEvent) != 1
        || content.count(endEvent) != 1) {
        throw ProtocolError(QStringLiteral("content must contain exactly one VCALENDAR and one VEVENT"));
    }

    const auto calendar = KCalendarCore::MemoryCalendar::Ptr(new KCalendarCore::MemoryCalendar(QTimeZone::utc()));
    KCalendarCore::ICalFormat converter;
    if (!converter.fromString(calendar, content)) {
        throw ProtocolError(QStringLiteral("invalid VCALENDAR content"));
    }
    const KCalendarCore::Event::List events = calendar->rawEvents();
    if (events.size() != 1 || !calendar->rawTodos().isEmpty() || !calendar->rawJournals().isEmpty()) {
        throw ProtocolError(QStringLiteral("content must parse to exactly one event and no todo or journal"));
    }
    if (events.constFirst()->uid().isEmpty()) {
        throw ProtocolError(QStringLiteral("event UID must not be empty"));
    }
    return events.constFirst();
}

KContacts::Addressee parseContact(const QString &content)
{
    static const QRegularExpression beginCard(QStringLiteral("(?im)^BEGIN:VCARD[\\t ]*\\r?$"));
    static const QRegularExpression endCard(QStringLiteral("(?im)^END:VCARD[\\t ]*\\r?$"));
    if (content.count(beginCard) != 1 || content.count(endCard) != 1) {
        throw ProtocolError(QStringLiteral("content must contain exactly one vCard"));
    }
    KContacts::VCardConverter converter;
    const KContacts::Addressee::List contacts = converter.parseVCards(content.toUtf8());
    if (contacts.size() != 1 || contacts.constFirst().isEmpty() || contacts.constFirst().uid().isEmpty()) {
        throw ProtocolError(QStringLiteral("content must parse to one non-empty vCard with a UID"));
    }
    return contacts.constFirst();
}

void setParsedPayload(Akonadi::Item &item, Kind kind, const QString &content)
{
    if (kind == Kind::Calendar) {
        item.setMimeType(KCalendarCore::Event::eventMimeType());
        item.setPayload<KCalendarCore::Incidence::Ptr>(parseEvent(content));
    } else {
        item.setMimeType(KContacts::Addressee::mimeType());
        item.setPayload<KContacts::Addressee>(parseContact(content));
    }
}

QString logicalUidFromContent(Kind kind, const QString &content)
{
    return kind == Kind::Calendar ? parseEvent(content)->uid() : parseContact(content).uid();
}

QJsonObject statusCommand()
{
    auto job = std::make_unique<Akonadi::CollectionFetchJob>(Akonadi::Collection::root(), Akonadi::CollectionFetchJob::Recursive);
    job->fetchScope().setAncestorRetrieval(Akonadi::CollectionFetchScope::All);
    runJob(job.get(), QStringLiteral("collection listing"));

    QHash<qint64, Akonadi::Collection> byId;
    for (const Akonadi::Collection &collection : job->collections()) {
        byId.insert(collection.id(), collection);
    }

    const uint generation = Akonadi::ServerManager::generation();
    const QString instance = Akonadi::ServerManager::instanceIdentifier();
    QJsonArray calendars;
    QJsonArray addressbooks;
    for (const Akonadi::Collection &collection : job->collections()) {
        if (collection.isVirtual() || (!supportsKind(collection, Kind::Calendar) && !supportsKind(collection, Kind::AddressBook))) {
            continue;
        }

        QStringList context;
        qint64 parentId = collection.parentCollection().id();
        QSet<qint64> seen;
        while (parentId > 0 && byId.contains(parentId) && !seen.contains(parentId)) {
            seen.insert(parentId);
            const Akonadi::Collection parent = byId.value(parentId);
            if (!parent.displayName().isEmpty()) {
                context.prepend(parent.displayName());
            }
            parentId = parent.parentCollection().id();
        }
        if (!collection.resource().isEmpty() && (context.isEmpty() || context.constFirst() != collection.resource())) {
            context.prepend(collection.resource());
        }
        QString ownName = collection.displayName().isEmpty() ? collection.name() : collection.displayName();
        if (ownName.isEmpty()) {
            ownName = QStringLiteral("Collection %1").arg(collection.id());
        }
        context.append(ownName);
        const QString fullName = context.join(QStringLiteral(" / ")).left(4096);

        const Akonadi::Collection::Rights rights = collection.rights();
        QJsonArray rightNames;
        rightNames.append(QStringLiteral("read"));
        if (rights & Akonadi::Collection::CanCreateItem) {
            rightNames.append(QStringLiteral("create"));
        }
        if (rights & Akonadi::Collection::CanChangeItem) {
            rightNames.append(QStringLiteral("change"));
        }
        if (rights & Akonadi::Collection::CanDeleteItem) {
            rightNames.append(QStringLiteral("delete"));
        }
        const QJsonObject result{
            {QStringLiteral("collection"), jsonInteger(collection.id(), QStringLiteral("collection id"))},
            {QStringLiteral("name"), fullName},
            {QStringLiteral("generation"), static_cast<double>(generation)},
            {QStringLiteral("instance"), instance},
            {QStringLiteral("rights"), rightNames},
        };
        if (supportsKind(collection, Kind::Calendar)) {
            calendars.append(result);
        }
        if (supportsKind(collection, Kind::AddressBook)) {
            addressbooks.append(result);
        }
    }
    return {{QStringLiteral("ok"), true},
            {QStringLiteral("calendars"), calendars},
            {QStringLiteral("addressbooks"), addressbooks}};
}

QJsonObject snapshotCommand(const QJsonObject &request)
{
    requireKeys(request, {"command", "kind", "collection", "generation", "instance"});
    verifyServerBinding(request);
    const Kind kind = parseKind(request);
    const qint64 collectionId = integerValue(request, "collection", 1, MaxExactJsonInteger);
    const Akonadi::Collection collection = fetchCollection(collectionId, kind);
    const Akonadi::Item::List fetched = fetchStableCollectionItems(collection);
    verifyServerBinding(request);

    // Construct the entire response before writing anything; any bad payload rejects the snapshot.
    QJsonArray items;
    qint64 contentSize = 0;
    for (const Akonadi::Item &item : fetched) {
        if (item.storageCollectionId() != collection.id()) {
            throw ProtocolError(QStringLiteral("snapshot returned an item owned by another collection"));
        }
        if (kind == Kind::Calendar && isIgnoredCalendarItem(item)) {
            continue;
        }
        const QJsonObject result = metadata(item, kind, true);
        contentSize += result.value(QStringLiteral("content")).toString().toUtf8().size();
        if (contentSize > MaxOutput - 1024 * 1024) {
            throw ProtocolError(QStringLiteral("serialized collection exceeds the output limit"));
        }
        items.append(result);
    }
    return {{QStringLiteral("ok"), true},
            {QStringLiteral("complete"), true},
            {QStringLiteral("items"), items}};
}

QJsonObject createCommand(const QJsonObject &request)
{
    requireKeys(request, {"command", "kind", "collection", "generation", "instance", "content"});
    verifyServerBinding(request);
    const Kind kind = parseKind(request);
    const qint64 collectionId = integerValue(request, "collection", 1, MaxExactJsonInteger);
    const QString content = stringValue(request, "content");
    const Akonadi::Collection collection = fetchCollection(collectionId, kind);
    if (!(collection.rights() & Akonadi::Collection::CanCreateItem)) {
        throw ProtocolError(QStringLiteral("collection does not permit item creation"));
    }

    Akonadi::Item item;
    setParsedPayload(item, kind, content);
    const QString logicalUid = logicalUidFromContent(kind, content);
    for (const Akonadi::Item &existing : fetchStableCollectionItems(collection)) {
        if ((kind != Kind::Calendar || !isIgnoredCalendarItem(existing))
            && itemUid(existing, kind) == logicalUid) {
            throw ProtocolError(QStringLiteral("an item with this logical UID already exists"));
        }
    }
    item.setGid(logicalUid);
    auto job = std::make_unique<Akonadi::ItemCreateJob>(item, collection);
    runJob(job.get(), QStringLiteral("item creation"));
    const Akonadi::Item created = fetchItem(job->item().id());
    verifyServerBinding(request);
    if (created.storageCollectionId() != collection.id()) {
        throw ProtocolError(QStringLiteral("created item is not owned by the requested collection"));
    }
    return {{QStringLiteral("ok"), true},
            {QStringLiteral("item"), metadata(created, kind, true)}};
}

QJsonObject modifyCommand(const QJsonObject &request)
{
    requireKeys(request, {"command", "kind", "collection", "generation", "instance", "id", "revision", "content"});
    verifyServerBinding(request);
    const Kind kind = parseKind(request);
    const qint64 collectionId = integerValue(request, "collection", 1, MaxExactJsonInteger);
    const qint64 itemId = integerValue(request, "id", 1, MaxExactJsonInteger);
    const int revision = static_cast<int>(integerValue(request, "revision", 0, std::numeric_limits<int>::max()));
    const QString content = stringValue(request, "content");
    const Akonadi::Collection collection = fetchCollection(collectionId, kind);
    if (!(collection.rights() & Akonadi::Collection::CanChangeItem)) {
        throw ProtocolError(QStringLiteral("collection does not permit item changes"));
    }

    Akonadi::Item item = fetchItem(itemId);
    if (item.storageCollectionId() != collection.id()) {
        throw ProtocolError(QStringLiteral("item is not owned by the requested collection"));
    }
    const QString oldUid = itemUid(item, kind);
    if (item.revision() != revision) {
        throw ProtocolError(QStringLiteral("item revision does not match"));
    }
    if (logicalUidFromContent(kind, content) != oldUid) {
        throw ProtocolError(QStringLiteral("logical UID cannot be changed"));
    }
    setParsedPayload(item, kind, content);

    auto job = std::make_unique<Akonadi::ItemModifyJob>(item);
    job->disableAutomaticConflictHandling();
    runJob(job.get(), QStringLiteral("item modification"));
    const Akonadi::Item modified = fetchItem(job->item().id());
    verifyServerBinding(request);
    return {{QStringLiteral("ok"), true},
            {QStringLiteral("item"), metadata(modified, kind, true)}};
}

QJsonObject deleteCommand(const QJsonObject &request)
{
    requireKeys(request, {"command", "kind", "collection", "generation", "instance", "id", "revision"});
    verifyServerBinding(request);
    const Kind kind = parseKind(request);
    const qint64 collectionId = integerValue(request, "collection", 1, MaxExactJsonInteger);
    const qint64 itemId = integerValue(request, "id", 1, MaxExactJsonInteger);
    const int revision = static_cast<int>(integerValue(request, "revision", 0, std::numeric_limits<int>::max()));
    const Akonadi::Collection collection = fetchCollection(collectionId, kind);
    if (!(collection.rights() & Akonadi::Collection::CanDeleteItem)) {
        throw ProtocolError(QStringLiteral("collection does not permit item deletion"));
    }
    const Akonadi::Item item = fetchItem(itemId);
    if (item.storageCollectionId() != collection.id()) {
        throw ProtocolError(QStringLiteral("item is not owned by the requested collection"));
    }
    if (item.revision() != revision) {
        throw ProtocolError(QStringLiteral("item revision does not match"));
    }
    itemUid(item, kind);
    auto job = std::make_unique<Akonadi::ItemDeleteJob>(item);
    runJob(job.get(), QStringLiteral("item deletion"));
    verifyServerBinding(request);
    return {{QStringLiteral("ok"), true}};
}

QJsonObject existsCommand(const QJsonObject &request)
{
    requireKeys(request, {"command", "kind", "collection", "generation", "instance", "uid"});
    verifyServerBinding(request);
    const Kind kind = parseKind(request);
    const qint64 collectionId = integerValue(request, "collection", 1, MaxExactJsonInteger);
    const QString uid = stringValue(request, "uid");
    const Akonadi::Collection collection = fetchCollection(collectionId, kind);
    const Akonadi::Item::List items = fetchStableCollectionItems(collection);
    bool exists = false;
    for (const Akonadi::Item &item : items) {
        if (item.storageCollectionId() != collection.id()) {
            throw ProtocolError(QStringLiteral("snapshot returned an item owned by another collection"));
        }
        if (kind == Kind::Calendar && isIgnoredCalendarItem(item)) {
            continue;
        }
        if (itemUid(item, kind) == uid) {
            exists = true;
        }
    }
    verifyServerBinding(request);
    return {{QStringLiteral("ok"), true}, {QStringLiteral("exists"), exists}};
}

QJsonObject dispatch(const QJsonObject &request)
{
    const QJsonValue commandValue = request.value(QStringLiteral("command"));
    if (!commandValue.isString() || commandValue.toString().isEmpty()) {
        throw ProtocolError(QStringLiteral("'command' must be a non-empty string"));
    }
    const QString command = commandValue.toString();
    if (QStringList{QStringLiteral("status"), QStringLiteral("snapshot"), QStringLiteral("create"),
                    QStringLiteral("modify"), QStringLiteral("delete"), QStringLiteral("exists")}.contains(command)) {
        // Query the bus daemon only. Creating the first KDE job can start a
        // missing server, so never create a job without an existing service.
        auto bus = QDBusConnection::sessionBus().interface();
        for (const auto service : {Akonadi::ServerManager::Server, Akonadi::ServerManager::Control}) {
            if (!bus || !bus->isServiceRegistered(Akonadi::ServerManager::serviceName(service)).value()) {
                throw ProtocolError(QStringLiteral("KDE service is not running; open your configured KDE application first"));
            }
        }
    }
    if (command == QLatin1String("status")) {
        requireKeys(request, {"command"});
        return statusCommand();
    }
    if (command == QLatin1String("snapshot")) {
        return snapshotCommand(request);
    }
    if (command == QLatin1String("create")) {
        return createCommand(request);
    }
    if (command == QLatin1String("modify")) {
        return modifyCommand(request);
    }
    if (command == QLatin1String("delete")) {
        return deleteCommand(request);
    }
    if (command == QLatin1String("exists")) {
        return existsCommand(request);
    }
    throw ProtocolError(QStringLiteral("unsupported command '%1'").arg(command));
}

QByteArray readRequest()
{
    QFile input;
    if (!input.open(stdin, QIODevice::ReadOnly)) {
        throw ProtocolError(QStringLiteral("cannot open stdin"));
    }
    QByteArray data;
    while (!input.atEnd()) {
        const QByteArray chunk = input.read(64 * 1024);
        if (chunk.isEmpty() && input.error() != QFileDevice::NoError) {
            throw ProtocolError(QStringLiteral("cannot read stdin"));
        }
        data.append(chunk);
        if (data.size() > MaxInput) {
            throw ProtocolError(QStringLiteral("input exceeds 16 MiB"));
        }
    }
    return data;
}

void writeResponse(const QJsonObject &response)
{
    const QByteArray data = QJsonDocument(response).toJson(QJsonDocument::Compact) + '\n';
    if (data.size() > MaxOutput) {
        throw ProtocolError(QStringLiteral("output exceeds 64 MiB"));
    }
    QFile output;
    if (!output.open(stdout, QIODevice::WriteOnly)) {
        throw ProtocolError(QStringLiteral("cannot open stdout"));
    }
    qint64 offset = 0;
    while (offset < data.size()) {
        const qint64 written = output.write(data.constData() + offset, data.size() - offset);
        if (written <= 0) {
            throw ProtocolError(QStringLiteral("cannot write stdout"));
        }
        offset += written;
    }
    output.flush();
}
}

int main(int argc, char **argv)
{
    QCoreApplication application(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("magnolie-akonadi-helper"));

    try {
        if (application.arguments() == QStringList{application.arguments().first(), QStringLiteral("--self-check")}) {
            // No session, bus lookup, resource enumeration or account setup.
            writeResponse({{QStringLiteral("ok"), true}, {QStringLiteral("selfCheck"), true}});
            return 0;
        }
        const QByteArray input = readRequest();
        QJsonParseError parseError;
        const QJsonDocument document = QJsonDocument::fromJson(input, &parseError);
        if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
            throw ProtocolError(QStringLiteral("stdin must contain exactly one JSON object: %1").arg(parseError.errorString()));
        }
        writeResponse(dispatch(document.object()));
        return 0;
    } catch (const ProtocolError &error) {
        try {
            writeResponse({{QStringLiteral("ok"), false}, {QStringLiteral("error"), QString::fromUtf8(error.what())}});
        } catch (...) {
        }
        return 1;
    } catch (const std::exception &error) {
        try {
            writeResponse({{QStringLiteral("ok"), false}, {QStringLiteral("error"), QStringLiteral("internal error: %1").arg(QString::fromUtf8(error.what()))}});
        } catch (...) {
        }
        return 1;
    }
}
