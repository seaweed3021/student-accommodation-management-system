-- RoomSphere data model (PostgreSQL). Draft v0 - Mitesh Chand Thakur.
-- Runs on RDS PostgreSQL in a private subnet; only the app container connects.

CREATE TABLE users (
    user_id      SERIAL PRIMARY KEY,
    cognito_sub  VARCHAR(64)  NOT NULL UNIQUE,      -- id issued by Amazon Cognito
    full_name    VARCHAR(100) NOT NULL,
    email        VARCHAR(255) NOT NULL UNIQUE,
    phone        VARCHAR(30),
    role         VARCHAR(10)  NOT NULL CHECK (role IN ('landlord', 'student')),
    created_at   TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE TABLE properties (
    property_id  SERIAL PRIMARY KEY,
    landlord_id  INT          NOT NULL REFERENCES users(user_id),
    name         VARCHAR(100) NOT NULL,
    address      VARCHAR(200) NOT NULL,
    city         VARCHAR(80)  NOT NULL,
    description  TEXT
);

CREATE TABLE rooms (
    room_id        SERIAL PRIMARY KEY,
    property_id    INT           NOT NULL REFERENCES properties(property_id),
    title          VARCHAR(100)  NOT NULL,
    description    TEXT,
    monthly_rent   NUMERIC(8,2)  NOT NULL CHECK (monthly_rent > 0),
    status         VARCHAR(12)   NOT NULL DEFAULT 'available'
                   CHECK (status IN ('available', 'occupied', 'unavailable')),
    available_from DATE
);

CREATE TABLE room_photos (
    photo_id  SERIAL PRIMARY KEY,
    room_id   INT          NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    s3_key    VARCHAR(255) NOT NULL                 -- object key in the private S3 bucket
);

CREATE TABLE applications (
    application_id SERIAL PRIMARY KEY,
    room_id        INT         NOT NULL REFERENCES rooms(room_id),
    student_id     INT         NOT NULL REFERENCES users(user_id),
    status         VARCHAR(12) NOT NULL DEFAULT 'submitted'
                   CHECK (status IN ('submitted', 'under_review', 'approved', 'rejected', 'withdrawn')),
    move_in_date   DATE        NOT NULL,
    message        TEXT,
    landlord_note  TEXT,                            -- internal, never shown to the student
    submitted_at   TIMESTAMP   NOT NULL DEFAULT now(),
    decided_at     TIMESTAMP
);

CREATE TABLE tenancies (
    tenancy_id     SERIAL PRIMARY KEY,
    application_id INT  NOT NULL UNIQUE REFERENCES applications(application_id),
    room_id        INT  NOT NULL REFERENCES rooms(room_id),
    student_id     INT  NOT NULL REFERENCES users(user_id),
    start_date     DATE NOT NULL,
    end_date       DATE
);

CREATE TABLE maintenance_requests (
    request_id   SERIAL PRIMARY KEY,
    tenancy_id   INT          NOT NULL REFERENCES tenancies(tenancy_id),
    title        VARCHAR(100) NOT NULL,
    description  TEXT         NOT NULL,
    priority     VARCHAR(6)   NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    status       VARCHAR(12)  NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'in_progress', 'resolved')),
    created_at   TIMESTAMP    NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMP
);

CREATE INDEX idx_rooms_status        ON rooms(status);
CREATE INDEX idx_applications_student ON applications(student_id);
CREATE INDEX idx_applications_status  ON applications(status);
CREATE INDEX idx_maintenance_status   ON maintenance_requests(status);
