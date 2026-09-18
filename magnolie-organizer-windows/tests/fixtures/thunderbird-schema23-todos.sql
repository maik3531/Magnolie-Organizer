CREATE TABLE cal_todos (
    cal_id TEXT, id TEXT, last_modified INTEGER, title TEXT, priority TEXT,
    ical_status TEXT, flags INTEGER, todo_due INTEGER, todo_due_tz TEXT,
    percent_complete TEXT, recurrence_id INTEGER, recurrence_id_tz TEXT
);
INSERT INTO cal_todos VALUES
    ('c', 'todo-broken', 1, 'Kaputt', 'hoch', 'NEEDS-ACTION', 0, 'kein-datum', 'UTC', 'offen', NULL, NULL),
    ('c', 'todo-valid', 2, 'Thunderbird Aufgabe', '1', 'NEEDS-ACTION', 0, 1788336000000000, 'UTC', '0', NULL, NULL);
