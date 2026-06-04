import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Product, Cart, Order

import os
from werkzeug.utils import secure_filename
app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.config['SECRET_KEY'] = 'bangdedshop123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# =====================
# DATABASE
# =====================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# =====================
# HOME
# =====================

@app.route("/")
def home():
    products = Product.query.all()
    return render_template("home.html", products=products)

# =====================
# REGISTER
# =====================

@app.route("/register", methods=["GET","POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        user = User(
            username=username,
            email=email,
            password=password
        )

        db.session.add(user)
        db.session.commit()

        flash("Registrasi berhasil")
        return redirect("/login")

    return render_template("register.html")

# =====================
# LOGIN
# =====================

@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password,password):

            login_user(user)

            if user.role == "admin":
                return redirect("/admin")

            return redirect("/dashboard")

        flash("Login gagal")

    return render_template("login.html")

# =====================
# LOGOUT
# =====================

@app.route("/logout")
@login_required
def logout():

    logout_user()
    return redirect("/")

# =====================
# USER DASHBOARD
# =====================

@app.route("/dashboard")
@login_required
def dashboard():

    products = Product.query.all()

    return render_template(
        "user/dashboard.html",
        products=products
    )

# =====================
# ADMIN DASHBOARD
# =====================

@app.route("/admin")
@login_required
def admin():

    if current_user.role != "admin":
        return redirect("/dashboard")

    products = Product.query.all()

    return render_template(
        "admin/dashboard.html",
        products=products
    )

=====================
DATA USER
=====================

@app.route("/admin/users")
@login_required
def admin_users():

if current_user.role != "admin":
    return redirect("/dashboard")

users = User.query.all()

return render_template(
    "admin/users.html",
    users=users
)

=====================
HAPUS USER
=====================

@app.route("/delete-user/"int:id" (int:id)")
@login_required
def delete_user(id):

if current_user.role != "admin":
    return redirect("/dashboard")

user = User.query.get_or_404(id)

if user.role == "admin":
    flash("Admin tidak bisa dihapus")
    return redirect("/admin/users")

db.session.delete(user)
db.session.commit()

return redirect("/admin/users")

=====================
LAPORAN
=====================

@app.route("/admin/reports")
@login_required
def admin_reports():

if current_user.role != "admin":
    return redirect("/dashboard")

total_user = User.query.count()
total_produk = Product.query.count()
total_order = Order.query.count()

return render_template(
    "admin/reports.html",
    total_user=total_user,
    total_produk=total_produk,
    total_order=total_order
)

=====================
PENGATURAN
=====================

@app.route("/admin/settings")
@login_required
def admin_settings():

if current_user.role != "admin":
    return redirect("/dashboard")

return render_template(
    "admin/settings.html"
)    

# =====================
# CRUD PRODUK
# =====================

@app.route("/add-product", methods=["POST"])
@login_required
def add_product():

    if current_user.role != "admin":
        return redirect("/")

    name = request.form["name"]
    price = request.form["price"]
    stock = request.form["stock"]

    image_file = request.files["image"]

    filename = ""

    if image_file:

        filename = secure_filename(
            image_file.filename
        )

        image_file.save(
            os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )
        )

    product = Product(
        name=name,
        price=price,
        stock=stock,
        image=filename
    )

    db.session.add(product)
    db.session.commit()

    return redirect("/admin")

@app.route("/delete-product/<int:id>")
@login_required
def delete_product(id):

    if current_user.role != "admin":
        return redirect("/")

    product = Product.query.get(id)

    db.session.delete(product)
    db.session.commit()

    return redirect("/admin")

# =====================
# RUN
# =====================

@app.route("/edit-product/<int:id>", methods=["GET","POST"])
@login_required
def edit_product(id):

    product = Product.query.get_or_404(id)

    if request.method == "POST":

        product.name = request.form["name"]
        product.price = request.form["price"]
        product.stock = request.form["stock"]

        db.session.commit()

        return redirect("/admin")

    return f"""
    <h2>Edit Produk</h2>

    <form method='POST'>

    <input name='name' value='{product.name}'><br><br>

    <input name='price' value='{product.price}'><br><br>

    <input name='stock' value='{product.stock}'><br><br>

    <button>Simpan</button>

    </form>
    """

if __name__ == "__main__":

    with app.app_context():

        db.create_all()

        admin = User.query.filter_by(email="admin@gmail.com").first()

        if not admin:

            admin_user = User(
                username="Administrator",
                email="admin@gmail.com",
                password=generate_password_hash("admin123"),
                role="admin"
            )

            db.session.add(admin_user)
            db.session.commit()

@app.route("/add-cart/<int:id>")
@login_required
def add_cart(id):

    product = Product.query.get(id)

    cart = Cart(
        user_id=current_user.id,
        product_id=product.id,
        quantity=1
    )

    db.session.add(cart)
    db.session.commit()

    return redirect("/cart")

@app.route("/cart")
@login_required
def cart():

    carts = Cart.query.filter_by(
        user_id=current_user.id
    ).all()

    total = 0

    for item in carts:
        total += int(item.product.price)

    return render_template(
        "user/cart.html",
        carts=carts,
        total=total
    )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=True)