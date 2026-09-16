// Exercise the actual protocol serializers without starting Akonadi or D-Bus.
#define main helperMain
#include "main.cpp"
#undef main

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    const QString event = QStringLiteral(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Magnolie//Test//EN\r\n"
        "BEGIN:VEVENT\r\nUID:isolated-event\r\nDTSTART:20260911T120000Z\r\n"
        "DTEND:20260911T130000Z\r\nSUMMARY:Synthetic event\r\n"
        "RRULE:FREQ=DAILY;COUNT=2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n");
    Akonadi::Item calendarItem;
    calendarItem.setPayload<KCalendarCore::Incidence::Ptr>(parseEvent(event));
    const QString serialized = serializeItem(calendarItem, Kind::Calendar);
    if (!serialized.contains(QStringLiteral("BEGIN:VCALENDAR"))
        || !serialized.contains(QStringLiteral("RRULE:"))
        || parseEvent(serialized)->uid() != QStringLiteral("isolated-event")) {
        return 1;
    }
    const QString card = QStringLiteral(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:isolated-contact\r\n"
        "FN:Synthetic Contact\r\nN:Contact;Synthetic;;;\r\n"
        "EMAIL:synthetic@example.invalid\r\nEND:VCARD\r\n");
    Akonadi::Item contactItem;
    contactItem.setPayload<KContacts::Addressee>(parseContact(card));
    const QString contact = serializeItem(contactItem, Kind::AddressBook);
    if (!contact.contains(QStringLiteral("VERSION:3.0"))
        || parseContact(contact).uid() != QStringLiteral("isolated-contact")
        || parseContact(contact).preferredEmail() != QStringLiteral("synthetic@example.invalid")) {
        return 1;
    }
    return 0;
}
