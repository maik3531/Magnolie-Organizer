// Opt-in native probe. The caller supplies a newly created synthetic collection.
#define main magnolie_helper_program_main
#include "main.cpp"
#undef main

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    try {
        if (argc != 2) throw std::runtime_error("pass one synthetic collection binding");
        auto binding = QJsonDocument::fromJson(argv[1]).object();
        if (binding.take(QStringLiteral("syntheticResource")).toString().isEmpty()) {
            throw std::runtime_error("synthetic collection binding required");
        }
        const Kind kind = parseKind(binding);
        const auto id = integerValue(binding, "collection", 1, MaxExactJsonInteger);
        const auto collection = fetchCollection(id, kind);
        const QString uid = QStringLiteral("guarded-delete-probe-") + QUuid::createUuid().toString(QUuid::WithoutBraces);
        const QString content = kind == Kind::Calendar
            ? QStringLiteral("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:") + uid
                + QStringLiteral("\r\nDTSTART:20261010T120000Z\r\nDTEND:20261010T130000Z\r\nSUMMARY:Synthetic guard\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
            : QStringLiteral("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:") + uid
                + QStringLiteral("\r\nFN:Synthetic guard\r\nN:Guard;Synthetic;;;\r\nEND:VCARD\r\n");
        auto create = binding;
        create.insert(QStringLiteral("command"), QStringLiteral("create"));
        create.insert(QStringLiteral("content"), content);
        const auto made = createCommand(create).value(QStringLiteral("item")).toObject();
        std::fprintf(stderr, "guard probe: created\n");
        const auto itemId = integerValue(made, "id", 1, MaxExactJsonInteger);
        const auto stale = fetchItem(itemId);
        auto modify = binding;
        modify.insert(QStringLiteral("command"), QStringLiteral("modify"));
        modify.insert(QStringLiteral("id"), static_cast<double>(itemId));
        modify.insert(QStringLiteral("revision"), stale.revision());
        modify.insert(QStringLiteral("content"), QString(content).replace(QStringLiteral("Synthetic guard"), QStringLiteral("Changed elsewhere")));
        modifyCommand(modify);
        std::fprintf(stderr, "guard probe: competing revision stored\n");
        bool rejected = false;
        try { deleteItemRevisionGuarded(stale, collection, []() {}); }
        catch (const std::exception &error) {
            rejected = QString::fromUtf8(error.what()).contains(QLatin1String("LLCONFLICT"));
            if (!rejected) throw;
        }
        if (!rejected || !metadata(fetchItem(itemId), kind, true).value(QStringLiteral("content")).toString().contains(QLatin1String("Changed elsewhere"))) {
            throw std::runtime_error("a post-fetch revision change was lost");
        }
        const auto current = fetchItem(itemId);
        std::fprintf(stderr, "guard probe: stale revision rejected\n");
        bool rolledBack = false;
        bool reachedCommitBarrier = false;
        try {
            deleteItemRevisionGuarded(current, collection, [&reachedCommitBarrier]() {
                reachedCommitBarrier = true;
                throw std::runtime_error("synthetic pre-commit binding failure");
            });
        } catch (const std::exception &error) {
            if (!reachedCommitBarrier) throw;
            rolledBack = true;
        }
        const auto restored = fetchItem(itemId);
        std::fprintf(stderr, "guard probe: rollback readback\n");
        if (!rolledBack || restored.revision() != current.revision()
            || metadata(restored, kind, true) != metadata(current, kind, true)) {
            throw std::runtime_error("failed guarded delete was not fully rolled back");
        }
        deleteItemRevisionGuarded(restored, collection, [&binding]() { verifyServerBinding(binding); });
        std::fprintf(stderr, "guard probe: current deletion committed\n");
        auto exists = binding;
        exists.insert(QStringLiteral("command"), QStringLiteral("exists"));
        exists.insert(QStringLiteral("uid"), uid);
        if (existsCommand(exists).value(QStringLiteral("exists")).toBool()) throw std::runtime_error("guarded deletion did not commit");
        std::puts("GUARDED DELETE PASS: stale revision rejected, complete rollback, current revision deleted");
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "Guarded delete probe failed: %s\n", error.what());
        return 1;
    }
}
