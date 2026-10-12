-- Sample data for testing schema.sql locally. Fake data only - never load into the real database.
INSERT INTO users(cognito_sub,full_name,email,role) VALUES ('sub-l','Test Landlord','l@x.com','landlord'),('sub-s','Test Student','s@x.com','student');
INSERT INTO properties(landlord_id,name,address,city) VALUES (1,'Maple House','1 Maple St','Toronto');
INSERT INTO rooms(property_id,title,monthly_rent,available_from) VALUES (1,'Room A',850,'2026-11-01');
INSERT INTO applications(room_id,student_id,move_in_date) VALUES (1,2,'2026-11-01');
UPDATE applications SET status='approved', decided_at=now() WHERE application_id=1;
INSERT INTO tenancies(application_id,room_id,student_id,start_date) VALUES (1,1,2,'2026-11-01');
INSERT INTO maintenance_requests(tenancy_id,title,description) VALUES (1,'Leaky tap','Kitchen tap drips');
SELECT r.title, r.monthly_rent, a.status, m.title AS issue FROM rooms r JOIN applications a USING(room_id) JOIN tenancies t USING(application_id) JOIN maintenance_requests m USING(tenancy_id);
