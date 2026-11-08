-- Schema for a NEW database. Do not use to reset a live database.

CREATE TABLE users (
	id INTEGER NOT NULL,
	username VARCHAR(64) NOT NULL,
	password_hash VARCHAR(256) NOT NULL,
	role VARCHAR(16) NOT NULL,
	active BOOLEAN NOT NULL,
	token_version INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (username)
);

CREATE TABLE devices (
	id INTEGER NOT NULL,
	name VARCHAR(100) NOT NULL,
	code VARCHAR(64) NOT NULL,
	status VARCHAR(32) NOT NULL,
	firmware VARCHAR(64),
	PRIMARY KEY (id),
	UNIQUE (code)
);

CREATE TABLE slots (
	id INTEGER NOT NULL,
	name VARCHAR(32) NOT NULL,
	occupied BOOLEAN,
	PRIMARY KEY (id),
	UNIQUE (name)
);

CREATE TABLE alerts (
	id INTEGER NOT NULL,
	message VARCHAR(500) NOT NULL,
	acknowledged BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE sensor_telemetry (
	id INTEGER NOT NULL,
	device_code VARCHAR(64) NOT NULL,
	uptime_s INTEGER NOT NULL,
	do_level INTEGER NOT NULL,
	detected BOOLEAN NOT NULL,
	received_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_sensor_telemetry_device_code ON sensor_telemetry (device_code);

CREATE TABLE seen_packets (
	device_code VARCHAR(64) NOT NULL,
	boot_id VARCHAR(32) NOT NULL,
	seq INTEGER NOT NULL,
	received_at DATETIME NOT NULL,
	PRIMARY KEY (device_code, boot_id, seq)
);

CREATE TABLE audit_logs (
	id INTEGER NOT NULL,
	actor_id INTEGER NOT NULL,
	action VARCHAR(500) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE TABLE sensor_slot_readings (
	telemetry_id INTEGER NOT NULL,
	slot_name VARCHAR(32) NOT NULL,
	do_level INTEGER NOT NULL,
	occupied BOOLEAN NOT NULL,
	PRIMARY KEY (telemetry_id, slot_name),
	FOREIGN KEY(telemetry_id) REFERENCES sensor_telemetry (id)
);

CREATE TABLE device_details (
	device_id INTEGER NOT NULL,
	location VARCHAR(100) NOT NULL,
	hardware VARCHAR(64),
	last_seen DATETIME,
	activated_at DATETIME NOT NULL,
	report_interval_ms INTEGER NOT NULL,
	offline_timeout_s INTEGER NOT NULL,
	broker_provisioned BOOLEAN NOT NULL,
	offline_alert BOOLEAN NOT NULL,
	full_alert BOOLEAN NOT NULL,
	connection_state VARCHAR(16) NOT NULL,
	forced_offline BOOLEAN NOT NULL,
	fault VARCHAR(200),
	last_boot_id VARCHAR(32),
	last_seq INTEGER,
	PRIMARY KEY (device_id),
	FOREIGN KEY(device_id) REFERENCES devices (id)
);

CREATE TABLE device_grants (
	device_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	can_control BOOLEAN NOT NULL,
	can_configure BOOLEAN NOT NULL,
	PRIMARY KEY (device_id, user_id),
	FOREIGN KEY(device_id) REFERENCES devices (id),
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE device_slots (
	slot_name VARCHAR(32) NOT NULL,
	device_id INTEGER NOT NULL,
	gpio INTEGER NOT NULL,
	PRIMARY KEY (slot_name),
	FOREIGN KEY(slot_name) REFERENCES slots (name),
	FOREIGN KEY(device_id) REFERENCES devices (id)
);

CREATE INDEX ix_device_slots_device_id ON device_slots (device_id);

CREATE TABLE device_boots (
	device_id INTEGER NOT NULL,
	boot_id VARCHAR(32) NOT NULL,
	PRIMARY KEY (device_id, boot_id),
	FOREIGN KEY(device_id) REFERENCES devices (id)
);

CREATE TABLE parking_events (
	id INTEGER NOT NULL,
	device_id INTEGER NOT NULL,
	slot_name VARCHAR(32) NOT NULL,
	kind VARCHAR(24) NOT NULL,
	occupied BOOLEAN,
	occurred_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(device_id) REFERENCES devices (id)
);

CREATE INDEX ix_parking_events_occurred_at ON parking_events (occurred_at);

CREATE INDEX ix_parking_events_device_id ON parking_events (device_id);

CREATE TABLE alert_details (
	alert_id INTEGER NOT NULL,
	device_id INTEGER NOT NULL,
	kind VARCHAR(32) NOT NULL,
	severity VARCHAR(16) NOT NULL,
	active_key VARCHAR(100),
	resolved_at DATETIME,
	acknowledged_by INTEGER,
	acknowledged_at DATETIME,
	PRIMARY KEY (alert_id),
	FOREIGN KEY(alert_id) REFERENCES alerts (id),
	FOREIGN KEY(device_id) REFERENCES devices (id),
	UNIQUE (active_key),
	FOREIGN KEY(acknowledged_by) REFERENCES users (id)
);

CREATE INDEX ix_alert_details_device_id ON alert_details (device_id);

CREATE TABLE device_commands (
	id VARCHAR(32) NOT NULL,
	device_id INTEGER NOT NULL,
	actor_id INTEGER NOT NULL,
	action VARCHAR(32) NOT NULL,
	arguments JSON NOT NULL,
	status VARCHAR(24) NOT NULL,
	created_at DATETIME NOT NULL,
	expires_at DATETIME NOT NULL,
	last_sent_at DATETIME,
	completed_at DATETIME,
	attempts INTEGER NOT NULL,
	error VARCHAR(200),
	result JSON,
	idempotency_key VARCHAR(64),
	target_boot_id VARCHAR(32),
	uptime_deadline_s INTEGER,
	PRIMARY KEY (id),
	UNIQUE (actor_id, idempotency_key),
	FOREIGN KEY(device_id) REFERENCES devices (id),
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_device_commands_device_id ON device_commands (device_id);

CREATE TABLE live_telemetry (
	device_code VARCHAR(64) NOT NULL,
	received_at DATETIME NOT NULL,
	expires_at DATETIME NOT NULL,
	accounted_until DATETIME NOT NULL,
	invalidated_at DATETIME,
	history_at DATETIME,
	history_id INTEGER,
	uptime_s INTEGER NOT NULL,
	levels JSON NOT NULL,
	operational BOOLEAN NOT NULL,
	boot_id VARCHAR(32),
	seq INTEGER,
	PRIMARY KEY (device_code)
);

CREATE TABLE hourly_occupancy (
	device_code VARCHAR(64) NOT NULL,
	slot_name VARCHAR(32) NOT NULL,
	hour DATETIME NOT NULL,
	occupied_s FLOAT NOT NULL,
	available_s FLOAT NOT NULL,
	unknown_s FLOAT NOT NULL,
	PRIMARY KEY (device_code, slot_name, hour)
);

CREATE TABLE storage_state (
	"key" VARCHAR(32) NOT NULL,
	at DATETIME NOT NULL,
	PRIMARY KEY ("key")
);
