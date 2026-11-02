-- Demo data for the API (fake). Loaded only when the init Lambda is invoked with {"seed": true}.
INSERT INTO users(cognito_sub,full_name,email,role) VALUES ('seed-landlord','Demo Landlord','landlord@example.com','landlord');
INSERT INTO properties(landlord_id,name,address,city,description) VALUES (1,'Maple House','1 Maple St','Toronto','Five-bedroom student house near transit');
INSERT INTO rooms(property_id,title,description,monthly_rent,status,available_from) VALUES
 (1,'Room A','Bright room with desk',850,'available','2026-12-01'),
 (1,'Room B','Quiet room, shared bath',790,'available','2026-12-01'),
 (1,'Room C','Large room, ensuite',900,'occupied',NULL)
