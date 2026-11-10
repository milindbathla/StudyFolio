# Local academic calendar

## From a turn to a suggestion

Classification covers assignments, quizzes, examinations, projects, registration, academic meetings, and explicit study milestones. Date interpretation requires an academic event and temporal evidence. The optional model can identify a verbatim title and date span in complex text. The local parser determines whether the date and time are valid. Questions and ordinary historical mentions are filtered.

Original expressions and the source message timestamp are preserved. The default zone is Asia/Kolkata. ISO dates, named months, relative days, weekdays, and 12/24-hour times are supported. A weekday denotes its next occurrence. On that weekday, “next Friday” refers to the following Friday. A yearless future date uses the source year, rolling forward if needed. Ambiguous numeric dates or incomplete phrases remain pending. Midnight needs explicit review. A missing time means an all-day date. Ambiguous and nonexistent daylight-saving times require the learner to choose a valid local time.

Timed records store UTC instants and their original timezone. All-day records store a civil date. Month and agenda filtering converts timed records to the configured display zone. Reprocessing uses the message's original time. Local time and UTC can fall on different calendar days.

## Decisions and revision history

Passive mentions normally create proposals. An unambiguous explicit command may confirm automatically. Settings control both policies. Ambiguous cases always require review. Only confirmed events populate the month grid, agenda, upcoming deadlines, chat calendar answers and ICS export.

Normalized titles, academic category, date/time, source identity and existing event records help detect duplicates. A source/segment key prevents another extraction of the same proposal. Repeated mentions link to the original suggestion, so replay cannot revive an obsolete date. A correction checks meaningful subject words, category and any stated prior date. A unique confirmed target receives a proposed revision. A date-only reschedule retains the existing clock time, duration and description. An updated pending proposal preserves its predecessor. Ambiguous confirmed targets require selection. A stale update is refused when the target revision has changed. Confirmation updates one event ID and increments its sequence. The history retains the old and new dates. Pending records can be rejected without altering the calendar.

Manual events can specify a description and same-day end time. The current UI handles individual events. Calendar notifications are the upcoming-deadline panel and in-app agenda while the app is open.

## Interchange

ICS export uses the icalendar library for escaping, CRLF line folding, stable UID, DTSTAMP and SEQUENCE. Timed events use UTC. All-day events export a DATE start and exclusive next-day end. Exported files can be opened in other calendar programs at the user's discretion.

CSV import accepts UTF-8 text with required `title,date` headers and optional `description,category,time`. Use ISO civil dates and one of the seven category names. Valid rows are accepted, identical events are reused, and invalid rows produce line-numbered feedback. CSV content is parsed as data without expression evaluation.

```csv
title,date,description,category
Mechanics quiz,2030-11-19,Review rotational dynamics,quiz
```
