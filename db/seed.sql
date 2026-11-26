-- Demo data for the API (fake). Loaded only when the init Lambda is invoked with {"seed": true}.
INSERT INTO users(cognito_sub,full_name,email,role) VALUES ('seed-landlord','Demo Landlord','landlord@example.com','landlord') ON CONFLICT (cognito_sub) DO NOTHING;
INSERT INTO properties(landlord_id,name,address,city,description)
SELECT user_id,'Maple House','1 Maple St','Toronto','Five-bedroom student house near transit' FROM users WHERE cognito_sub='seed-landlord';
INSERT INTO rooms(property_id,title,description,monthly_rent,status,available_from)
SELECT p.property_id, v.title, v.description, v.rent, v.status, v.available_from::date
FROM properties p, (VALUES
 ('Room A','Bright room with desk',850,'available','2026-12-01'),
 ('Room B','Quiet room, shared bath',790,'available','2026-12-01'),
 ('Room C','Large room, ensuite',900,'occupied',NULL)
) AS v(title,description,rent,status,available_from)
WHERE p.name='Maple House'
