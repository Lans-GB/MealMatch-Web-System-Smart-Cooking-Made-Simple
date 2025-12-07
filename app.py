"""
MealMatch - Updated app.py
Features added:
1. Persistent weekly meal plan (stored per-user with week_start date).
2. Cooking instructions for recipes (stored/displayed).
3. Export endpoints for weekly plan and recipes (CSV & JSON).
4. OOP structure for services, lambda usage, and error handling.
"""

import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, g, flash, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import json
import os
import io
import csv
from typing import List, Dict, Any

# Config
app = Flask(__name__)
app.secret_key = "dev-secret-change-this"  # change for production
DATABASE = "mealmatch.db"

# Custom exceptions
class DBError(Exception):
    pass

# Database
class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn = None

    def connect(self):
        if self._conn is None:
            need_init = not os.path.exists(self.path)
            self._conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
            self._conn.row_factory = sqlite3.Row
            if need_init:
                self._init_db()
        return self._conn

    def _init_db(self):
        try:
            with app.open_resource("schema.sql", mode="r") as f:
                self._conn.executescript(f.read())
            self._conn.commit()
        except Exception as e:
            raise DBError(f"Failed to initialize DB: {e}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def query(self, sql: str, args=(), one=False):
        try:
            cur = self.connect().execute(sql, args)
            rv = cur.fetchall()
            cur.close()
            return (rv[0] if rv else None) if one else rv
        except Exception as e:
            raise DBError(e)

    def execute(self, sql: str, args=()):
        try:
            cur = self.connect().execute(sql, args)
            self.connect().commit()
            return cur.lastrowid
        except Exception as e:
            raise DBError(e)

db = Database(DATABASE)

# Services (OOP)
class UserService:
    @staticmethod
    def get_current_user():
        uid = session.get("user_id")
        if not uid:
            return None
        return db.query("SELECT id, username, email, is_admin FROM users WHERE id = ?", (uid,), one=True)

    @staticmethod
    def create_user(username, email, password):
        pw_hash = generate_password_hash(password)
        try:
            return db.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                              (username, email, pw_hash))
        except sqlite3.IntegrityError as e:
            raise DBError("Username or email already exists.") from e

class IngredientService:
    @staticmethod
    def list_user_ingredients(user_id: int):
        return db.query("SELECT * FROM ingredients WHERE user_id = ? ORDER BY name", (user_id,))

    @staticmethod
    def add_ingredient(user_id: int, name: str, quantity: float, unit: str, notes: str):
        return db.execute("INSERT INTO ingredients (user_id, name, quantity, unit, notes) VALUES (?, ?, ?, ?, ?)",
                          (user_id, name, quantity, unit, notes))

    @staticmethod
    def get_ingredient(id:int, user_id:int):
        return db.query("SELECT * FROM ingredients WHERE id = ? AND user_id = ?", (id, user_id), one=True)

    @staticmethod
    def update_ingredient(id:int, name:str, quantity:float, unit:str, notes:str):
        return db.execute("UPDATE ingredients SET name = ?, quantity = ?, unit = ?, notes = ? WHERE id = ?",
                          (name, quantity, unit, notes, id))

    @staticmethod
    def delete_ingredient(id:int, user_id:int):
        return db.execute("DELETE FROM ingredients WHERE id = ? AND user_id = ?", (id, user_id))

class RecipeService:
    @staticmethod
    def list_all_recipes():
        return db.query("SELECT r.*, u.username as creator FROM recipes r LEFT JOIN users u ON r.created_by = u.id ORDER BY r.title")

    @staticmethod
    def create_recipe(title:str, description:str, instructions:str, created_by:int, ingredient_lines:List[str]):
        recipe_id = db.execute("INSERT INTO recipes (title, description, instructions, created_by) VALUES (?, ?, ?, ?)",
                      (title, description, instructions, created_by))
        for line in ingredient_lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 1 and parts[0]:
                name = parts[0]
                qty = float(parts[1]) if len(parts) > 1 and parts[1] else 1
                unit = parts[2] if len(parts) > 2 else "pcs"
                db.execute("INSERT INTO recipe_ingredients (recipe_id, ingredient_name, required_quantity, unit) VALUES (?, ?, ?, ?)",
                           (recipe_id, name, qty, unit))
        return recipe_id

    @staticmethod
    def get_recipe(id:int):
        rec = db.query("SELECT * FROM recipes WHERE id = ?", (id,), one=True)
        if not rec:
            return None
        r_ings = db.query("SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (id,))
        return rec, r_ings

    @staticmethod
    def update_recipe(id:int, title:str, description:str, instructions:str, ingredient_lines:List[str]):
        db.execute("UPDATE recipes SET title = ?, description = ?, instructions = ? WHERE id = ?",
                   (title, description, instructions, id))
        db.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (id,))
        for line in ingredient_lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 1 and parts[0]:
                name = parts[0]
                qty = float(parts[1]) if len(parts) > 1 and parts[1] else 1
                unit = parts[2] if len(parts) > 2 else "pcs"
                db.execute("INSERT INTO recipe_ingredients (recipe_id, ingredient_name, required_quantity, unit) VALUES (?, ?, ?, ?)",
                           (id, name, qty, unit))

    @staticmethod
    def delete_recipe(id:int):
        db.execute("DELETE FROM recipes WHERE id = ?", (id,))

class MealPlanService:
    """
    MealPlanService creates a weekly plan and stores it in mealplans table under week_start (ISO date).
    It will return existing plan for the same week if found.
    """
    @staticmethod
    def _get_week_start(a_date: date) -> date:
        # week starts on onday
        return a_date - timedelta(days=a_date.weekday())

    @staticmethod
    @staticmethod
    def get_or_create_weekly_plan(user_id:int) -> Dict[str, Any]:
        today = date.today()
        week_start = MealPlanService._get_week_start(today)
        week_start_iso = week_start.isoformat()

        # Check if user already has a plan with this week_start
        existing = db.query("SELECT * FROM mealplans WHERE user_id = ? AND week_start = ?", (user_id, week_start_iso), one=True)
        if existing:
            # parse stored JSON and return proper fields
            try:
                payload = json.loads(existing["plan_json"]) if existing["plan_json"] else {}
                plan = payload.get("plan", [])
                candidates = payload.get("candidates", [])
            except Exception:
                plan = []
                candidates = []
            return {"plan": plan, "generated_on": existing["generated_on"], "week_start": week_start_iso, "candidates": candidates}

        # else generate new plan and store it
        plan, candidates = MealPlanService._generate_plan(user_id)
        generated_on = datetime.now().isoformat()
        db.execute("INSERT INTO mealplans (user_id, generated_on, week_start, plan_json) VALUES (?, ?, ?, ?)",
                   (user_id, generated_on, week_start_iso, json.dumps({"plan": plan, "candidates": candidates})))
        return {"plan": plan, "generated_on": generated_on, "week_start": week_start_iso, "candidates": candidates}

    @staticmethod
    def _generate_plan(user_id:int):
        # Build inventory
        rows = db.query("SELECT name, quantity, unit FROM ingredients WHERE user_id = ?", (user_id,))
        inv = {}
        for r in rows:
            inv[r["name"].lower()] = {"quantity": r["quantity"], "unit": r["unit"]}

        # Fetch all recipes and compute match percentage
        recipes = db.query("SELECT * FROM recipes")
        recipe_list = []
        for rec in recipes:
            # Convert sqlite3.Row to dict and extract string values
            rec_dict = dict(rec)
            rec_ing_rows = db.query("SELECT * FROM recipe_ingredients WHERE recipe_id = ?", (rec_dict["id"],))
            total = len(rec_ing_rows)
            available = 0
            for ri in rec_ing_rows:
                name = ri["ingredient_name"].lower()
                required = ri["required_quantity"] or 0
                if name in inv and inv[name]["quantity"] >= required:
                    available += 1
            percent = (available / total * 100) if total > 0 else 0
            recipe_list.append({
                "id": rec_dict["id"],
                "title": str(rec_dict["title"]),  # Ensure it's a string
                "description": str(rec_dict.get("description", "")),
                "available": available,
                "total": total,
                "percent": percent
            })

        # candidates >= 50% (use lambda in sorting)
        candidates = list(filter(lambda r: r["total"] > 0 and r["percent"] >= 50, recipe_list))
        candidates.sort(key=lambda x: (-x["percent"], x["title"]))  # lambda used for sorting

        # make a weekly plan (7 days)
        plan = []
        i = 0
        while len(plan) < 7:
            if not candidates:
                plan.append({"day": len(plan) + 1, "title": "No suitable recipe", "match": 0})
            else:
                chosen = candidates[i % len(candidates)]
                plan.append({
                    "day": len(plan) + 1, 
                    "title": str(chosen["title"]),  # Ensure it's a string
                    "match": chosen["percent"], 
                    "recipe_id": chosen["id"]
                })
            i += 1
            if i > 100:  # safety
                break

        # reduce candidate data for storage
        slim_candidates = [
            {
                "id": c["id"], 
                "title": str(c["title"]),  # Ensure it's a string
                "percent": c["percent"], 
                "available": c["available"], 
                "total": c["total"]
            } 
            for c in candidates
        ]
        return plan, slim_candidates

#Helpers
def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not UserService.get_current_user():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

#Authentication
@app.route("/")
def index():
    if UserService.get_current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    try:
        if request.method == "POST":
            username = request.form["username"].strip()
            email = request.form["email"].strip()
            password = request.form["password"]
            if not username or not email or not password:
                flash("All fields required.", "danger")
                return render_template("register.html")
            UserService.create_user(username, email, password)
            flash("Account created. Please login.", "success")
            return redirect(url_for("login"))
    except DBError as e:
        flash(str(e), "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        user = db.query("SELECT * FROM users WHERE email = ?", (email,), one=True)
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

# Dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    user = UserService.get_current_user()
    ing_count = db.query("SELECT COUNT(*) as c FROM ingredients WHERE user_id = ?", (user["id"],), one=True)["c"]
    rec_count = db.query("SELECT COUNT(*) as c FROM recipes", (), one=True)["c"]
    return render_template("dashboard.html", user=user, ing_count=ing_count, rec_count=rec_count)

# Ingredients CRUD
@app.route("/ingredients")
@login_required
def ingredients():
    user = UserService.get_current_user()
    rows = IngredientService.list_user_ingredients(user["id"])
    return render_template("ingredients.html", ingredients=rows, user=user)

@app.route("/ingredients/add", methods=["GET", "POST"])
@login_required
def add_ingredient():
    user = UserService.get_current_user()
    if request.method == "POST":
        try:
            name = request.form["name"].strip()
            quantity = float(request.form.get("quantity") or 0)
            unit = request.form.get("unit") or "pcs"
            notes = request.form.get("notes") or ""
            if not name:
                flash("Ingredient name required.", "danger")
                return render_template("ingredient_form.html")
            IngredientService.add_ingredient(user["id"], name, quantity, unit, notes)
            flash("Ingredient added.", "success")
            return redirect(url_for("ingredients"))
        except Exception as e:
            flash(f"Error: {e}", "danger")
    return render_template("ingredient_form.html", action="Add")

@app.route("/ingredients/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_ingredient(id):
    user = UserService.get_current_user()
    ing = IngredientService.get_ingredient(id, user["id"])
    if not ing:
        flash("Ingredient not found.", "danger")
        return redirect(url_for("ingredients"))
    if request.method == "POST":
        try:
            name = request.form["name"].strip()
            quantity = float(request.form.get("quantity") or 0)
            unit = request.form.get("unit") or "pcs"
            notes = request.form.get("notes") or ""
            IngredientService.update_ingredient(id, name, quantity, unit, notes)
            flash("Ingredient updated.", "success")
            return redirect(url_for("ingredients"))
        except Exception as e:
            flash(f"Error: {e}", "danger")
    return render_template("ingredient_form.html", action="Edit", ingredient=ing)

@app.route("/ingredients/delete/<int:id>", methods=["POST"])
@login_required
def delete_ingredient(id):
    user = UserService.get_current_user()
    IngredientService.delete_ingredient(id, user["id"])
    flash("Ingredient deleted.", "info")
    return redirect(url_for("ingredients"))

# Recipes CRUD (include cooking instructions)
@app.route("/recipes")
@login_required
def recipes():
    rows = RecipeService.list_all_recipes()
    # group recipe ingredients by recipe id
    recipe_ingredients = {}
    for ri in db.query("SELECT * FROM recipe_ingredients"):
        recipe_ingredients.setdefault(ri["recipe_id"], []).append(ri)
    return render_template("recipes.html", recipes=rows, recipe_ingredients=recipe_ingredients)

@app.route("/recipes/add", methods=["GET", "POST"])
@login_required
def add_recipe():
    user = UserService.get_current_user()
    if request.method == "POST":
        try:
            title = request.form["title"].strip()
            description = request.form.get("description", "")
            instructions = request.form.get("instructions", "")
            raw_ing = request.form.get("ingredients_raw", "").strip()
            ingredient_lines = [l for l in raw_ing.splitlines() if l.strip()]
            if not title:
                flash("Recipe title required.", "danger")
                return render_template("recipe_form.html")
            RecipeService.create_recipe(title, description, instructions, user["id"], ingredient_lines)
            flash("Recipe added.", "success")
            return redirect(url_for("recipes"))
        except Exception as e:
            flash(f"Error: {e}", "danger")
    return render_template("recipe_form.html", action="Add")

@app.route("/recipes/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_recipe(id):
    user = UserService.get_current_user()
    rec_and_ings = RecipeService.get_recipe(id)
    if not rec_and_ings:
        flash("Recipe not found.", "danger")
        return redirect(url_for("recipes"))
    rec, r_ings = rec_and_ings
    if request.method == "POST":
        try:
            title = request.form["title"].strip()
            description = request.form.get("description", "")
            instructions = request.form.get("instructions", "")
            raw_ing = request.form.get("ingredients_raw", "").strip()
            ingredient_lines = [l for l in raw_ing.splitlines() if l.strip()]
            if not title:
                flash("Recipe title required.", "danger")
                return render_template("recipe_form.html", recipe=rec, recipe_ings=r_ings)
            RecipeService.update_recipe(id, title, description, instructions, ingredient_lines)
            flash("Recipe updated.", "success")
            return redirect(url_for("recipes"))
        except Exception as e:
            flash(f"Error: {e}", "danger")
    raw_text = "\n".join(f"{ri['ingredient_name']}|{ri['required_quantity']}|{ri['unit']}" for ri in r_ings)
    return render_template("recipe_form.html", action="Edit", recipe=rec, recipe_ings=r_ings, raw_text=raw_text)

@app.route("/recipes/delete/<int:id>", methods=["POST"])
@login_required
def delete_recipe(id):
    RecipeService.delete_recipe(id)
    flash("Recipe deleted.", "info")
    return redirect(url_for("recipes"))

# View a single recipe (with cooking instructions)
@app.route("/recipes/view/<int:id>")
@login_required
def view_recipe(id):
    rec_and_ings = RecipeService.get_recipe(id)
    if not rec_and_ings:
        flash("Recipe not found.", "danger")
        return redirect(url_for("recipes"))
    rec, r_ings = rec_and_ings
    return render_template("recipe_view.html", recipe=rec, ingredients=r_ings)

# Mealplan endpoints - same thru the week unless regen
@app.route("/mealplan")
@login_required
def mealplan():
    user = UserService.get_current_user()
    try:
        result = MealPlanService.get_or_create_weekly_plan(user["id"])
        # result contains plan, generated_on, week_start, optional candidates
        plan = result.get("plan", [])
        candidates = result.get("candidates", [])
        return render_template("mealplan.html", plan=plan, generated_on=result.get("generated_on"), week_start=result.get("week_start"), candidates=candidates)
    except DBError as e:
        flash(str(e), "danger")
        return redirect(url_for("dashboard"))

# Force-generate new plan (admin or user wants to regenerate for the current week)
@app.route("/mealplan/regenerate", methods=["POST"])
@login_required
def regenerate_mealplan():
    user = UserService.get_current_user()
    # delete existing plan for current week, then generate new
    week_start = MealPlanService._get_week_start(date.today()).isoformat()
    db.execute("DELETE FROM mealplans WHERE user_id = ? AND week_start = ?", (user["id"], week_start))
    flash("Old plan removed, new plan will be generated.", "info")
    return redirect(url_for("mealplan"))

#export meal plan
def csv_response(filename: str, rows: List[Dict[str, Any]], headers: List[str]):
    """
    Create a CSV response with given rows (list of dictionaries) and headers (list of field names).
    """
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(headers)
    for r in rows:
        writer.writerow([r.get(h, "") for h in headers])
    output = si.getvalue()
    return Response(output, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={filename}"})

@app.route("/export/recipe/<int:id>/<fmt>")
@login_required
def export_recipe(id:int, fmt:str):
    rec_and_ings = RecipeService.get_recipe(id)
    if not rec_and_ings:
        flash("Recipe not found.", "danger")
        return redirect(url_for("recipes"))
    rec, r_ings = rec_and_ings
    # build data
    data = {
        "id": rec["id"],
        "title": rec["title"],
        "description": rec["description"],
        "instructions": rec["instructions"],
        "ingredients": [{"name": ri["ingredient_name"], "qty": ri["required_quantity"], "unit": ri["unit"]} for ri in r_ings]
    }
    if fmt.lower() == "json":
        return Response(json.dumps(data, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": f"attachment;filename=recipe_{id}.json"})
    #create a CSV with header for recipe meta then ingredient rows
    if fmt.lower() == "csv":
        rows = []
        # meta row(s)
        rows.append({"field": "id", "value": rec["id"]})
        rows.append({"field": "title", "value": rec["title"]})
        rows.append({"field": "description", "value": rec["description"]})
        rows.append({"field": "instructions", "value": rec["instructions"]})
        # blank separator
        rows.append({"field": "", "value": ""})
        # ingredients header
        rows.append({"field": "ingredient", "qty": "qty", "unit": "unit"})
        for ing in data["ingredients"]:
            rows.append({"ingredient": ing["name"], "qty": ing["qty"], "unit": ing["unit"]})
        # write CSV
        si = io.StringIO()
        writer = csv.writer(si)
        # iterate rows and adapt fields
        for r in rows:
            if "ingredient" in r:
                writer.writerow([r.get("ingredient",""), r.get("qty",""), r.get("unit","")])
            else:
                writer.writerow([r.get("field",""), r.get("value","")])
        output = si.getvalue()
        return Response(output, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment;filename=recipe_{id}.csv"})
    flash("Unsupported format. Use json or csv.", "warning")
    return redirect(url_for("recipes"))

@app.route("/export/mealplan/<fmt>")
@login_required
def export_mealplan(fmt:str):
    user = UserService.get_current_user()
    # fetch current week plan
    week_start = MealPlanService._get_week_start(date.today()).isoformat()
    existing = db.query("SELECT * FROM mealplans WHERE user_id = ? AND week_start = ?", (user["id"], week_start), one=True)
    if not existing:
        flash("No meal plan for this week yet. Generate one first.", "warning")
        return redirect(url_for("mealplan"))
    try:
        payload = json.loads(existing["plan_json"])
    except Exception:
        payload = {"plan": []}
    plan = payload.get("plan") if isinstance(payload.get("plan"), list) else payload

    if fmt.lower() == "json":
        return Response(json.dumps({"week_start": existing["week_start"], "generated_on": existing["generated_on"], "plan": plan}, indent=2),
                        mimetype="application/json",
                        headers={"Content-Disposition": f"attachment;filename=mealplan_{existing['week_start']}.json"})
    if fmt.lower() == "csv":
        # creation for csv file
        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow(["day", "title", "match", "recipe_id"])
        for p in plan:
            writer.writerow([p.get("day",""), p.get("title",""), p.get("match",""), p.get("recipe_id","")])
        output = si.getvalue()
        return Response(output, mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment;filename=mealplan_{existing['week_start']}.csv"})
    flash("Unsupported format. Use json or csv.", "warning")
    return redirect(url_for("mealplan"))

#close db
@app.teardown_appcontext
def close_db(exception):
    try:
        db.close()
    except Exception:
        pass

if __name__ == "__main__":
    app.run(debug=True, port=5505)
