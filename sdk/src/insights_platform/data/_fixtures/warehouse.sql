create table compensation (
    employee_id text primary key,
    team text not null,
    base_salary integer not null,
    currency text not null default 'USD'
);

insert into compensation (employee_id, team, base_salary) values
    ('E001', 'people-analytics', 100000),
    ('E002', 'people-analytics', 110000),
    ('E003', 'finance', 95000),
    ('E004', 'finance', 105000);

create table headcount (
    team text not null,
    month text not null,
    count integer not null,
    primary key (team, month)
);

insert into headcount (team, month, count) values
    ('people-analytics', '2026-08', 2),
    ('people-analytics', '2026-09', 2),
    ('finance', '2026-08', 1),
    ('finance', '2026-09', 2);
