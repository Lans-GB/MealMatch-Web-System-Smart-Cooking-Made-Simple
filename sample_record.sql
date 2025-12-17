PRAGMA foreign_keys = ON;

-- Sample Records for users
INSERT INTO users (username, email, password_hash, is_admin)
VALUES
('workinghereusers', 'lance@gmail.com', 'hash_lance_123', 0),
('anna', 'anna@gmail.com', 'hash_anna_456', 1);

-- Sample Records for ingredients
INSERT INTO ingredients (user_id, name, quantity, unit, notes)
VALUES
(1, 'worksoningredients', 12, 'pcs', 'Fresh eggs'),
(2, 'Rice', 5, 'cups', 'White rice');

-- Sample Records for recipes
INSERT INTO recipes (title, description, instructions, created_by)
VALUES
('Pancake', 'I DEFINITELY WORK HERE AT RECIPES breakfast pancake', 'Mix ingredients and cook on pan', 1),
('Fried Rice', 'Quick rice meal', 'Stir-fry rice with seasoning', 2);

-- Sample Records for recipe_ingredients
INSERT INTO recipe_ingredients (recipe_id, ingredient_name, required_quantity, unit)
VALUES
(1, 'also here', 2, 'pcs'),
(2, 'Rice', 2, 'cups');

-- Sample Records for mealplans
INSERT INTO mealplans (user_id, generated_on, week_start, plan_json)
VALUES
(1, '2025-12-01', '2025-12-01', '{"{"plan": [{"day": 1, "title": "No suitable recipe", "match": 0}, {"day": 2, "title": "No suitable recipe", "match": 0}, {"day": 3, "title": "No suitable recipe", "match": 0}, {"day": 4, "title": "No suitable recipe", "match": 0}, {"day": 5, "title": "No suitable recipe", "match": 0}, {"day": 6, "title": "No suitable recipe", "match": 0}, {"day": 7, "title": "No suitable recipe", "match": 0}], "candidates": []}"}'),
