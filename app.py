import os
import random
import string
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Product, Cart, Order

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
# HELPER
# =====================

def gen_order_number():
    chars = string.ascii_uppercase + string.digits
    return "BDS-" + "".join(random.choices(chars, k=8))


# =====================
# USER LOADER
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

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        user = User(username=username, email=email, password=password)
        db.session.add(user)
        db.session.commit()
        flash("Registrasi berhasil", "success")
        return redirect("/login")
    return render_template("register.html")


# =====================
# LOGIN
# =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            if user.role == "admin":
                return redirect("/admin")
            return redirect("/dashboard")
        flash("Email atau password salah", "error")
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
    return render_template("user/dashboard.html", products=products)


# =====================
# KERANJANG (CART)
# =====================

@app.route("/add-cart/<int:id>")
@login_required
def add_cart(id):
    product = Product.query.get_or_404(id)

    # Cek apakah produk sudah ada di keranjang
    existing = Cart.query.filter_by(
        user_id=current_user.id,
        product_id=product.id
    ).first()

    if existing:
        existing.quantity += 1
    else:
        cart = Cart(
            user_id=current_user.id,
            product_id=product.id,
            quantity=1
        )
        db.session.add(cart)

    db.session.commit()
    flash(f"{product.name} ditambahkan ke keranjang 🛒", "success")
    return redirect(request.referrer or "/dashboard")


@app.route("/cart")
@login_required
def cart():
    carts = Cart.query.filter_by(user_id=current_user.id).all()
    total = sum(int(item.product.price) * item.quantity for item in carts)
    return render_template("user/cart.html", carts=carts, total=total)


@app.route("/cart/update/<int:id>", methods=["POST"])
@login_required
def update_cart(id):
    action = request.form.get("action")
    cart_item = Cart.query.get_or_404(id)

    if cart_item.user_id != current_user.id:
        return redirect("/cart")

    if action == "plus":
        if cart_item.quantity < cart_item.product.stock:
            cart_item.quantity += 1
    elif action == "minus":
        cart_item.quantity -= 1
        if cart_item.quantity <= 0:
            db.session.delete(cart_item)
    elif action == "remove":
        db.session.delete(cart_item)

    db.session.commit()
    return redirect("/cart")


@app.route("/cart/clear")
@login_required
def clear_cart():
    Cart.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash("Keranjang dikosongkan", "info")
    return redirect("/dashboard")


# =====================
# CHECKOUT
# =====================

@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    carts = Cart.query.filter_by(user_id=current_user.id).all()

    if not carts:
        flash("Keranjang kosong, tambah produk dulu!", "error")
        return redirect("/dashboard")

    total = sum(int(item.product.price) * item.quantity for item in carts)

    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        phone   = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        payment = request.form.get("payment", "transfer")

        errors = []
        if not name:    errors.append("Nama lengkap wajib diisi.")
        if not phone:   errors.append("Nomor HP wajib diisi.")
        if not address: errors.append("Alamat wajib diisi.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("user/checkout.html", carts=carts, total=total, form=request.form)

        order_number = gen_order_number()

        # Simpan setiap item sebagai Order
        for item in carts:
            order = Order(
                user_id=current_user.id,
                product_id=item.product_id,
                quantity=item.quantity,
                total_price=int(item.product.price) * item.quantity,
                # Tambahkan field ini ke model Order jika belum ada:
                # order_number, name, phone, address, payment, status
            )
            db.session.add(order)

        # Simpan info pesanan ke session untuk halaman sukses
        session["last_order"] = {
            "order_number": order_number,
            "name": name,
            "phone": phone,
            "address": address,
            "payment": payment,
            "total": total,
            "created_at": datetime.now().strftime("%d %b %Y, %H:%M"),
            "items": [
                {
                    "name": item.product.name,
                    "qty": item.quantity,
                    "subtotal": int(item.product.price) * item.quantity
                }
                for item in carts
            ]
        }

        # Hapus keranjang setelah checkout
        Cart.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()

        return redirect("/success")

    return render_template("user/checkout.html", carts=carts, total=total, form={})


# =====================
# SUCCESS
# =====================

@app.route("/success")
@login_required
def success():
    order = session.get("last_order")
    if not order:
        return redirect("/dashboard")
    return render_template("user/success.html", order=order)


# =========================
# ADMIN DASHBOARD
# =========================

@app.route("/admin")
@login_required
def admin():
    if current_user.role != "admin":
        return redirect("/dashboard")
    products = Product.query.all()
    return render_template("admin/dashboard.html", products=products)


@app.route("/admin/users")
@login_required
def admin_users():
    if current_user.role != "admin":
        return redirect("/dashboard")
    users = User.query.all()
    return render_template("admin/users.html", users=users)


@app.route("/admin/reports")
@login_required
def admin_reports():
    if current_user.role != "admin":
        return redirect("/dashboard")
    orders = Order.query.all()
    return render_template("admin/reports.html", orders=orders)


@app.route("/admin/settings")
@login_required
def admin_settings():
    if current_user.role != "admin":
        return redirect("/dashboard")
    return render_template("admin/settings.html")


# =========================
# HAPUS USER
# =========================

@app.route("/delete-user/<int:id>")
@login_required
def delete_user(id):
    if current_user.role != "admin":
        return redirect("/dashboard")
    user = User.query.get_or_404(id)
    if user.role == "admin":
        flash("Admin tidak bisa dihapus", "error")
        return redirect("/admin/users")
    db.session.delete(user)
    db.session.commit()
    flash("User berhasil dihapus", "success")
    return redirect("/admin/users")


# =========================
# CRUD PRODUK
# =========================

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
    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        image_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    product = Product(name=name, price=price, stock=stock, image=filename)
    db.session.add(product)
    db.session.commit()
    flash("Produk berhasil ditambahkan", "success")
    return redirect("/admin")


@app.route("/delete-product/<int:id>")
@login_required
def delete_product(id):
    if current_user.role != "admin":
        return redirect("/")
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash("Produk berhasil dihapus", "success")
    return redirect("/admin")


@app.route("/edit-product/<int:id>", methods=["GET", "POST"])
@login_required
def edit_product(id):
    if current_user.role != "admin":
        return redirect("/")
    product = Product.query.get_or_404(id)
    if request.method == "POST":
        product.name = request.form["name"]
        product.price = request.form["price"]
        product.stock = request.form["stock"]
        db.session.commit()
        flash("Produk berhasil diupdate", "success")
        return redirect("/admin")
    return render_template("admin/edit_product.html", product=product)


# =====================
# RUN
# =====================

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
    app.run(debug=True)