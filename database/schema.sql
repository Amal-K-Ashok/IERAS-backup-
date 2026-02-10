-- Accident table
create table accidents (
    id uuid primary key default gen_random_uuid(),
    camera_id text,
    latitude float,
    longitude float,
    severity text,
    timestamp timestamptz default now(),
    video_url text,
    status text default 'PENDING'
);

-- Ambulance table
create table ambulances (
    id uuid primary key default gen_random_uuid(),
    driver_name text,
    latitude float,
    longitude float,
    available boolean default true
);
