# app.py
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, g, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json
import os

app = Flask(__name__)
app.secret_key = "dev-secret-change-this"  # change for production
DATABASE = "mealmatch.db"

# -----------------------
# Database helpers
# -----------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        need_init = not os.path.exists(DATABASE)
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        if need_init:
            init_db(db)
    return db

def init_db(db):
    with app.open_resource("schema.sql", mode="r") as f:
        db.executescript(f.read())
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def modify_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid

# -----------------------
# Authentication helpers
# -----------------------
def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = query_db("SELECT id, username, email, is_admin FROM users WHERE id = ?", (user_id,), one=True)
    return user

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

# -----------------------
# Routes: Auth
# -----------------------
@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        if not username or not email or not password:
            flash("All fields required.", "danger")
            return render_template("register.html")
        pw_hash = generate_password_hash(password)
        try:
            modify_db("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                      (username, email, pw_hash))
            flash("Account created. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        user = query_db("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# Simple "forgot password" flow: verify username + email and allow reset
@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip()
        user = query_db("SELECT * FROM users WHERE username = ? AND email = ?", (username, email), one=True)
        if not user:
            flash("No matching user found.", "danger")
            return render_template("forgot.html")
        # For simplicity: let them set new password right away
        newpw = request.form.get("new_password")
        if newpw:
            pw_hash = generate_password_hash(newpw)
            modify_db("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user["id"]))
            flash("Password reset. Please login.", "success")
            return redirect(url_for("login"))
        else:
            flash("Enter a new password to reset.", "info")
    return render_template("forgot.html")

# -----------------------
# Dashboard
# -----------------------
@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    # show counts
    ing_count = query_db("SELECT COUNT(*) as c FROM ingredients WHERE user_id = ?", (user["id"],), one=True)["c"]
    rec_count = query_db("SELECT COUNT(*) as c FROM recipes", (), one=True)["c"]
    return render_template("dashboard.html", user=user, ing_count=ing_count, rec_count=rec_count)

# -----------------------
# Ingredients CRUD (user-specific)
# -----------------------
@app.route("/ingredients")
@login_required
def ingredients():
    user = current_user()
    rows = query_db("SELECT * FROM ingredients WHERE user_id = ? ORDER BY name", (user["id"],))
    return render_template("ingredients.html", ingredients=rows, user=user)

@app.route("/ingredients/add", methods=["GET", "POST"])
@login_required
def add_ingredient():
    user = current_user()
    if request.method == "POST":
        name = request.form["name"].strip()
        quantity = float(request.form.get("quantity") or 0)
        unit = request.form.get("unit") or "pcs"
        notes = request.form.get("notes") or ""
        if not name:
            flash("Ingredient name required.", "danger")
            return render_template("ingredient_form.html")
        modify_db("INSERT INTO ingredients (user_id, name, quantity, unit, notes) VALUES (?, ?, ?, ?, ?)",
                  (user["id"], name, quantity, unit, notes))
        flash("Ingredient added.", "success")
        return redirect(url_for("ingredients"))
    return render_template("ingredient_form.html", action="Add")

@app.route("/ingredients/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_ingredient(id):
    user = current_user()
    ing = query_db("SELECT * FROM ingredients WHERE id = ? AND user_id = ?", (id, user["id"]), one=True)
    if not ing:
        flash("Ingredient not found.", "danger")
        return redirect(url_for("ingredients"))
    if request.method == "POST":
        name = request.form["name"].strip()
        quantity = float(request.form.get("quantity") or 0)
        unit = request.form.get("unit") or "pcs"
        notes = request.form.get("notes") or ""
        modify_db("UPDATE ingredients SET name = ?, quantity = ?, unit = ?, notes = ? WHERE id = ?",
                  (name, quantity, unit, notes, id))
        flash("Ingredient updated.", "success")
        return redirect(url_for("ingredients"))
    return render_template("ingredient_form.html", action="Edit", ingredient=ing)

@app.route("/ingredients/delete/<int:id>", methods=["POST"])
@login_required
def delete_ingredient(id):
    user = current_user()
    modify_db("DELETE FROM ingredients WHERE id = ? AND user_id = ?", (id, user["id"]))
    flash("Ingredient deleted.", "info")
    return redirect(url_for("ingredients"))

# -----------------------
# Recipes CRUD (visible to all users)
# -----------------------
@app.route("/recipes")
@login_required
def recipes():
    rows = query_db("SELECT r.*, u.username as creator FROM recipes r LEFT JOIN users u ON r.created_by = u.id ORDER BY r.title")
    # get ingredients grouped by recipe id
    ingredients = {}
    for ri in query_db("SELECT * FROM recipe_ingredients"):
        ingredients.setdefault(ri["recipe_id"], []).append(ri)
    return render_template("recipes.html", recipes=rows, recipe_ingredients=ingredients)

@app.route("/recipes/add", methods=["GET", "POST"])
@login_required
def add_recipe():
    user = current_user()
    if request.method == "POST":
        title = request.form["title"].strip()
        description = request.form.get("description", "")
        instructions = request.form.get("instructions", "")
        # ingredients are submitted as comma-separated lines: name|qty|unit
        raw_ing = request.form.get("ingredients_raw", "").strip()
        if not title:
            flash("Recipe title required.", "danger")
            return render_template("recipe_form.html")
        recipe_id = modify_db("INSERT INTO recipes (title, description, instructions, created_by) VALUES (?, ?, ?, ?)",
                      (title, description, instructions, user["id"]))
        if raw_ing:
            for line in raw_ing.splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 1 and parts[0]:
                    name = parts[0]
                    qty = float(parts[1]) if len(parts) > 1 and parts[1] else 1
                    unit = parts[2] if len(parts) > 2 else "pcs"
                    modify_db("INSERT INTO recipe_ingredients (recipe_id, ingredient_name, required_quantity, unit) VALUES (?, ?, ?, ?)",
                              (recipe_id, name, qty, unit))
        flash("Recipe added.", "success")
        return redirect(url_for("recipes"))
    return render_template("recipe_form.html", action="Add")

@app.route("/recipes/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_recipe(id):
    rec = query_db("SELECT * FROM recipes WHERE id = ?", (id,), one=True)
    if not rec:
        flash("Recipe not found.", "danger")
        return redirect(url_for("recipes"))
    # load ingredients
    r_ings = query_db("SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (id,))
    if request.method == "POST":
        title = request.form["title"].strip()
        description = request.form.get("description", "")
        instructions = request.form.get("instructions", "")
        raw_ing = request.form.get("ingredients_raw", "").strip()
        if not title:
            flash("Recipe title required.", "danger")
            return render_template("recipe_form.html", recipe=rec, recipe_ings=r_ings)
        modify_db("UPDATE recipes SET title = ?, description = ?, instructions = ? WHERE id = ?",
                  (title, description, instructions, id))
        # delete old ingredients and insert new list
        modify_db("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (id,))
        if raw_ing:
            for line in raw_ing.splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 1 and parts[0]:
                    name = parts[0]
                    qty = float(parts[1]) if len(parts) > 1 and parts[1] else 1
                    unit = parts[2] if len(parts) > 2 else "pcs"
                    modify_db("INSERT INTO recipe_ingredients (recipe_id, ingredient_name, required_quantity, unit) VALUES (?, ?, ?, ?)",
                              (id, name, qty, unit))
        flash("Recipe updated.", "success")
        return redirect(url_for("recipes"))
    # create raw text for textarea: name|qty|unit per line
    raw_text = "\n".join(f"{ri['ingredient_name']}|{ri['required_quantity']}|{ri['unit']}" for ri in r_ings)
    return render_template("recipe_form.html", action="Edit", recipe=rec, recipe_ings=r_ings, raw_text=raw_text)

@app.route("/recipes/delete/<int:id>", methods=["POST"])
@login_required
def delete_recipe(id):
    modify_db("DELETE FROM recipes WHERE id = ?", (id,))
    flash("Recipe deleted.", "info")
    return redirect(url_for("recipes"))

# -----------------------
# Meal plan generator (weekly)
# -----------------------
@app.route("/mealplan")
@login_required
def mealplan():
    user = current_user()
    # fetch user's ingredients (simple dictionary: name -> quantity)
    rows = query_db("SELECT name, quantity, unit FROM ingredients WHERE user_id = ?", (user["id"],))
    inv = {}
    for r in rows:
        inv[r["name"].lower()] = {"quantity": r["quantity"], "unit": r["unit"]}
    # fetch all recipes and their ingredients
    recipes = query_db("SELECT * FROM recipes")
    recipe_list = []
    for rec in recipes:
        rec_ing_rows = query_db("SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (rec["id"],))
        # compute available_count and total_count
        total = len(rec_ing_rows)
        available = 0
        # for each recipe ingredient, check if present in user's inventory
        for ri in rec_ing_rows:
            name = ri["ingredient_name"].lower()
            if name in inv and inv[name]["quantity"] >= (ri["required_quantity"] or 0):
                available += 1
        percent = (available / total * 100) if total > 0 else 0
        recipe_list.append({
            "id": rec["id"],
            "title": rec["title"],
            "description": rec["description"],
            "available": available,
            "total": total,
            "percent": percent
        })
    # filter recipes with at least 50% ingredients available
    candidates = [r for r in recipe_list if r["total"] > 0 and r["percent"] >= 50]
    # sort candidates by percent descending so best matches come first
    candidates.sort(key=lambda x: (-x["percent"], x["title"]))
    # make a weekly plan (7 days) by picking top 7 distinct recipes; if fewer than 7, allow repeats
    plan = []
    i = 0
    while len(plan) < 7:
        if not candidates:
            plan.append({"day": len(plan)+1, "title": "No suitable recipe", "match": 0})
        else:
            plan.append({"day": len(plan)+1, "title": candidates[i % len(candidates)]["title"],
                         "match": candidates[i % len(candidates)]["percent"]})
        i += 1
        if i > 100:  # safe-guard
            break
    generated_on = datetime.now().isoformat()
    return render_template("mealplan.html", plan=plan, generated_on=generated_on, candidates=candidates)

# -----------------------
# Run app
# -----------------------
if __name__ == "__main__":
    app.run(debug=True, port=5505)
