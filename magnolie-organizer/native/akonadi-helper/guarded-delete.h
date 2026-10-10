#pragma once

#include <Akonadi/Collection>
#include <Akonadi/Item>
#include <Akonadi/ItemDeleteJob>
#include <Akonadi/ItemFetchJob>
#include <Akonadi/ItemModifyJob>
#include <Akonadi/Session>
#include <Akonadi/TransactionSequence>
#include <QUuid>
#include <functional>
#include <memory>
#include <stdexcept>

// ItemDeleteJob carries no expected revision. The STORE below performs Akonadi's
// revision check while holding the server-side row lock until the outer
// transaction commits. Reasserting the existing GID sends STORE without changing
// content or queuing a payload-change notification for the subsequently deleted item.
// A dedicated session also guarantees rollback on any exception/disconnection.
inline void deleteItemRevisionGuarded(const Akonadi::Item &expected,
                                     const Akonadi::Collection &collection,
                                     const std::function<void()> &verifyBinding)
{
    if (!expected.hasPayload() || expected.gid().isEmpty() || expected.revision() < 0
        || expected.storageCollectionId() != collection.id()
        || !(collection.rights() & Akonadi::Collection::CanChangeItem)
        || !(collection.rights() & Akonadi::Collection::CanDeleteItem)) {
        throw std::runtime_error("revision-guarded deletion requires a complete item with GID and change/delete rights");
    }
    auto session = std::make_unique<Akonadi::Session>(
        QByteArray("magnolie-guarded-delete-") + QUuid::createUuid().toByteArray());
    auto transaction = std::make_unique<Akonadi::TransactionSequence>(session.get());
    transaction->setAutoDelete(false);
    transaction->setAutomaticCommittingEnabled(false);
    std::exception_ptr failure;
    std::string phase = "revision guard";
    auto guard = new Akonadi::ItemModifyJob(expected, transaction.get());
    guard->disableAutomaticConflictHandling();
    guard->setIgnorePayload(true);
    guard->setUpdateGid(true);
    QObject::connect(guard, &KJob::result, transaction.get(), [&](KJob *job) {
        if (job->error()) return; // TransactionSequence performs the rollback.
        phase = "locked ownership read";
        auto fetched = new Akonadi::ItemFetchJob(Akonadi::Item(expected.id()), transaction.get());
        QObject::connect(fetched, &KJob::result, transaction.get(), [&, fetched](KJob *read) {
            if (read->error()) return;
            if (fetched->items().size() != 1
                || fetched->items().first().storageCollectionId() != collection.id()) {
                failure = std::make_exception_ptr(std::runtime_error("item ownership changed during deletion"));
                transaction->rollback();
                return;
            }
            phase = "locked deletion";
            auto removed = new Akonadi::ItemDeleteJob(Akonadi::Item(expected.id()), transaction.get());
            QObject::connect(removed, &KJob::result, transaction.get(), [&](KJob *deleted) {
                if (deleted->error()) return;
                try {
                    verifyBinding();
                    phase = "deletion commit";
                    transaction->commit();
                } catch (...) {
                    failure = std::current_exception();
                    transaction->rollback();
                }
            });
        });
    });
    // Execute only the parent; TransactionSequence owns subjob scheduling and
    // completion, including the rollback triggered by a failing revision guard.
    const bool committed = transaction->exec();
    if (failure) std::rethrow_exception(failure);
    if (!committed) {
        throw std::runtime_error(phase + ": " + transaction->errorString().toUtf8().constData());
    }
}
