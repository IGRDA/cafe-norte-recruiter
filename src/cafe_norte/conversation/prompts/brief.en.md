# Brief and read-back sentences (ana_v16, en)

One `key: sentence` per line; `#` lines and blank lines are ignored. `{value}` is filled by
`conversation/brief.py`. `brief.es.md` has exactly the same keys.

intro: Here is what I have.
question: Is all of that correct?
name: Your name is {value}.
interest.yes: You are interested in the role.
interest.unsure: You are not sure whether you are interested.
interest.no: You are not interested in the role.
work_authorization.yes: You have permission to work.
work_authorization.unsure: You are not sure whether you have permission to work.
work_authorization.no: You do not have permission to work.
availability: You can work {days}, on the {shifts} shift, about {hours} hours a week.
availability_days: You can work {value}.
availability_shifts: On the {value} shift.
hours_per_week: About {value} hours a week.
earliest_start_date: You could start on {value}.
experience: Experience: {value}.
contact_phone: Your phone number is {value}.
followup: You have asked for someone from the team to get in touch with you.
unknown: {label}: you do not know.
declined: {label}: you would rather not say.
readback.contact_phone: I have your phone number as {value}. Is that correct?
readback.earliest_start_date: I have that you could start on {value}. Is that correct?
readback.slot: I have the interview at {store} on {value}, Madrid time. Shall I reserve it?
slots.intro: I have these interview slots at {store}:
slots.question: Which one suits you best?
slots.none: I have no free interview slots right now.
slot: {value}
review.check: Is that right?
slot_time: {date} at {time}

label.name: Name
label.interest: Interest
label.work_authorization: Permission to work
label.availability_days: Days
label.availability_shifts: Shifts
label.hours_per_week: Hours a week
label.earliest_start_date: Start date
label.experience: Experience
label.contact_phone: Phone

weekdays: Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday
months: January,February,March,April,May,June,July,August,September,October,November,December
and: and
date: {weekday} {day} {month} {year}
