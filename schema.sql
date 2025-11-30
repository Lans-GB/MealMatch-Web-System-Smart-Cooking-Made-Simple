-- schema.sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, -- owner of this ingredient (inventory)
    name TEXT NOT NULL,
    quantity REAL DEFAULT 0,
    unit TEXT DEFAULT 'pcs',
    notes TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    instructions TEXT,
    created_by INTEGER, -- user id of creator (nullable)
    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
);

-- each recipe can have many ingredients with quantity needed
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    ingredient_name TEXT NOT NULL,
    required_quantity REAL DEFAULT 1,
    unit TEXT DEFAULT 'pcs',
    FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);

-- optionally store meal plan history (not used in basic demo)
CREATE TABLE IF NOT EXISTS mealplans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    generated_on TEXT NOT NULL,
    plan_json TEXT, -- JSON string of the plan
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
