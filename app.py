import os
import random
import string
from datetime import datetime
from io import BytesIO

from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, flash, session, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Product, Cart, Order, OrderItem

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

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


# ── Helper ────────────────────────────────────────────────────────────

def gen_order_number():
    return "BDS-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

def fmt_rupiah(n):
    return "Rp {:,}".format(int(n)).replace(",", ".")


# ── User Loader ───────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ── HOME ──────────────────────────────────────────────────────────────

@app.route("/")
def home():
    products = Product.query.all()
    return render_template("home.html", products=products)


# ── REGISTER ──────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email    = request.form["email"]
        password = generate_password_hash(request.form["password"])

        # Cek email sudah terdaftar
        if User.query.filter_by(email=email).first():
            flash("Email sudah terdaftar, gunakan email lain.", "error")
            return render_template("register.html")

        db.session.add(User(username=username, email=email, password=password))
        db.session.commit()
        flash("Registrasi berhasil, silakan login.", "success")
        return redirect("/login")
    return render_template("register.html")


# ── LOGIN ─────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect("/admin" if user.role == "admin" else "/dashboard")
        flash("Email atau password salah", "error")
    return render_template("login.html")


# ── LOGOUT ────────────────────────────────────────────────────────────

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")


# ── USER DASHBOARD ────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    products = Product.query.all()
    return render_template("user/dashboard.html", products=products)


# ── KERANJANG ─────────────────────────────────────────────────────────

@app.route("/add-cart/<int:id>")
@login_required
def add_cart(id):
    product = Product.query.get_or_404(id)
    existing = Cart.query.filter_by(user_id=current_user.id, product_id=product.id).first()
    if existing:
        existing.quantity += 1
    else:
        db.session.add(Cart(user_id=current_user.id, product_id=product.id, quantity=1))
    db.session.commit()
    flash(f"{product.name} ditambahkan ke keranjang 🛒", "success")
    return redirect(request.referrer or "/dashboard")


@app.route("/cart")
@login_required
def cart():
    carts = Cart.query.filter_by(user_id=current_user.id).all()
    total = sum(int(i.product.price) * i.quantity for i in carts)
    return render_template("user/cart.html", carts=carts, total=total)


@app.route("/cart/update/<int:id>", methods=["POST"])
@login_required
def update_cart(id):
    action = request.form.get("action")
    item   = Cart.query.get_or_404(id)
    if item.user_id != current_user.id:
        return redirect("/cart")
    if action == "plus":
        if item.quantity < item.product.stock:
            item.quantity += 1
    elif action == "minus":
        item.quantity -= 1
        if item.quantity <= 0:
            db.session.delete(item)
    elif action == "remove":
        db.session.delete(item)
    db.session.commit()
    return redirect("/cart")


@app.route("/cart/clear")
@login_required
def clear_cart():
    Cart.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash("Keranjang dikosongkan", "info")
    return redirect("/dashboard")


# ── CHECKOUT ──────────────────────────────────────────────────────────

@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    carts = Cart.query.filter_by(user_id=current_user.id).all()
    if not carts:
        flash("Keranjang kosong!", "error")
        return redirect("/dashboard")

    total = sum(int(i.product.price) * i.quantity for i in carts)

    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        phone   = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        payment = request.form.get("payment", "transfer")

        errors = []
        if not name:    errors.append("Nama wajib diisi.")
        if not phone:   errors.append("No. HP wajib diisi.")
        if not address: errors.append("Alamat wajib diisi.")
        if errors:
            for e in errors: flash(e, "error")
            return render_template("user/checkout.html", carts=carts, total=total, form=request.form)

        order_number = gen_order_number()

        # Simpan Order ke database
        order = Order(
            order_number=order_number,
            user_id=current_user.id,
            total=total,
            name=name, phone=phone, address=address,
            payment=payment, status="Menunggu"
        )
        db.session.add(order)
        db.session.flush()  # agar order.id tersedia

        # Simpan item pesanan
        items_data = []
        for i in carts:
            subtotal = int(i.product.price) * i.quantity
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=i.product_id,
                quantity=i.quantity,
                subtotal=subtotal
            ))
            items_data.append({
                "name": i.product.name,
                "qty": i.quantity,
                "subtotal": subtotal
            })

        Cart.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()

        # Simpan ke session untuk halaman sukses
        session["last_order"] = {
            "order_id":     order.id,
            "order_number": order_number,
            "name":         name,
            "phone":        phone,
            "address":      address,
            "payment":      payment,
            "total":        total,
            "created_at":   datetime.now().strftime("%d %b %Y, %H:%M"),
            "items":        items_data
        }
        return redirect("/success")

    return render_template("user/checkout.html", carts=carts, total=total, form={})


# ── SUCCESS ───────────────────────────────────────────────────────────

@app.route("/success")
@login_required
def success():
    order = session.get("last_order")
    if not order:
        return redirect("/dashboard")
    return render_template("user/success.html", order=order)


# ── DOWNLOAD STRUK PDF ────────────────────────────────────────────────

@app.route("/struk/<int:order_id>")
@login_required
def download_struk(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id and current_user.role != "admin":
        return redirect("/dashboard")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles  = getSampleStyleSheet()
    title_s = ParagraphStyle("t",  fontSize=20, fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=4)
    sub_s   = ParagraphStyle("s",  fontSize=10, fontName="Helvetica",      alignment=TA_CENTER, spaceAfter=2, textColor=colors.grey)
    sec_s   = ParagraphStyle("sc", fontSize=11, fontName="Helvetica-Bold", spaceAfter=6, textColor=colors.HexColor("#475569"))
    struk_s = ParagraphStyle("st", fontSize=14, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#2563eb"), spaceAfter=6)

    payment_label = {"transfer": "Transfer Bank", "qris": "QRIS", "cod": "COD"}.get(order.payment, order.payment)
    created = order.created_at.strftime("%d %b %Y, %H:%M") if order.created_at else "-"

    story = []

    # Header
    story.append(Paragraph("Bang-DedSHOP", title_s))
    story.append(Paragraph("Website Toko Online Berbasis Flask", sub_s))
    story.append(Paragraph("Universitas Hamzanwadi © 2026", sub_s))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#0f172a")))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("STRUK PEMBAYARAN", struk_s))
    story.append(Spacer(1, 0.2*cm))

    # Info pesanan
    info_data = [
        ["No. Pesanan",  ":", order.order_number],
        ["Tanggal",      ":", created],
        ["Status",       ":", order.status],
        ["Metode Bayar", ":", payment_label],
    ]
    t = Table(info_data, colWidths=[4*cm, 0.5*cm, None])
    t.setStyle(TableStyle([
        ("FONTNAME", (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    story.append(Spacer(1, 0.3*cm))

    # Info pembeli
    story.append(Paragraph("DATA PEMBELI", sec_s))
    buyer_data = [
        ["Nama",   ":", order.name],
        ["No. HP", ":", order.phone],
        ["Alamat", ":", order.address],
    ]
    t2 = Table(buyer_data, colWidths=[4*cm, 0.5*cm, None])
    t2.setStyle(TableStyle([
        ("FONTNAME", (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("VALIGN", (0,0),(-1,-1), "TOP"),
    ]))
    story.append(t2)
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    story.append(Spacer(1, 0.3*cm))

    # Tabel produk
    story.append(Paragraph("DETAIL PRODUK", sec_s))
    rows = [["No", "Produk", "Qty", "Harga", "Subtotal"]]
    for idx, item in enumerate(order.items, 1):
        harga = int(item.product.price) if item.product else 0
        rows.append([str(idx), item.product.name if item.product else "-",
                     str(item.quantity), fmt_rupiah(harga), fmt_rupiah(item.subtotal)])

    t3 = Table(rows, colWidths=[1*cm, None, 1.5*cm, 3.5*cm, 3.5*cm])
    t3.setStyle(TableStyle([
        ("BACKGROUND",     (0,0),(-1,0),  colors.HexColor("#0f172a")),
        ("TEXTCOLOR",      (0,0),(-1,0),  colors.white),
        ("FONTNAME",       (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",       (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",       (0,0),(-1,-1), 10),
        ("ALIGN",          (2,0),(4,-1),  "RIGHT"),
        ("ALIGN",          (0,0),(0,-1),  "CENTER"),
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID",           (0,0),(-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ("BOTTOMPADDING",  (0,0),(-1,-1), 6),
        ("TOPPADDING",     (0,0),(-1,-1), 6),
    ]))
    story.append(t3)
    story.append(Spacer(1, 0.3*cm))

    # Total
    t4 = Table([["", "Ongkir :", "Gratis"],
                ["", "TOTAL  :", fmt_rupiah(order.total)]],
               colWidths=[None, 3*cm, 3.5*cm])
    t4.setStyle(TableStyle([
        ("FONTNAME",  (1,0),(1,-1), "Helvetica-Bold"),
        ("FONTNAME",  (2,1),(2,1),  "Helvetica-Bold"),
        ("FONTSIZE",  (2,1),(2,1),  13),
        ("TEXTCOLOR", (2,1),(2,1),  colors.HexColor("#2563eb")),
        ("ALIGN",     (1,0),(-1,-1), "RIGHT"),
        ("TOPPADDING",(0,0),(-1,-1), 4),
    ]))
    story.append(t4)
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    story.append(Spacer(1, 0.3*cm))

    # Instruksi bayar
    if order.payment == "transfer":
        story.append(Paragraph("INSTRUKSI TRANSFER", ParagraphStyle("tr", fontSize=11, fontName="Helvetica-Bold", spaceAfter=6, textColor=colors.HexColor("#1d4ed8"))))
        bank_rows = [["BCA",":", "1234567890 (a.n. Bang Ded)"],
                     ["BNI",":", "9876543210 (a.n. Bang Ded)"],
                     ["Mandiri",":", "1122334455 (a.n. Bang Ded)"],
                     ["BRI",":", "0098765432 (a.n. Bang Ded)"]]
        tb = Table(bank_rows, colWidths=[2.5*cm, 0.5*cm, None])
        tb.setStyle(TableStyle([("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
        story.append(tb)
        story.append(Paragraph("* Transfer nominal tepat: " + fmt_rupiah(order.total),
                               ParagraphStyle("w", fontSize=9, textColor=colors.HexColor("#3b82f6"))))
    elif order.payment == "qris":
        story.append(Paragraph("Scan QRIS melalui aplikasi dompet digital Anda.",
                               ParagraphStyle("q", fontSize=10, textColor=colors.HexColor("#15803d"))))
    else:
        story.append(Paragraph(f"Siapkan uang {fmt_rupiah(order.total)} saat kurir tiba. Estimasi 2-3 hari kerja.",
                               ParagraphStyle("c", fontSize=10, textColor=colors.HexColor("#92400e"))))

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Terima kasih telah berbelanja di Bang-DedSHOP!",
                           ParagraphStyle("th", fontSize=11, fontName="Helvetica-Bold",
                                          alignment=TA_CENTER, textColor=colors.HexColor("#16a34a"))))

    doc.build(story)
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=struk-{order.order_number}.pdf"
    return response


# ── ADMIN ─────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
def admin():
    if current_user.role != "admin": return redirect("/dashboard")
    return render_template("admin/dashboard.html", products=Product.query.all())

@app.route("/admin/users")
@login_required
def admin_users():
    if current_user.role != "admin": return redirect("/dashboard")
    return render_template("admin/users.html", users=User.query.all())

@app.route("/admin/reports")
@login_required
def admin_reports():
    if current_user.role != "admin": return redirect("/dashboard")
    return render_template("admin/reports.html", orders=Order.query.order_by(Order.id.desc()).all())

@app.route("/admin/settings")
@login_required
def admin_settings():
    if current_user.role != "admin": return redirect("/dashboard")
    return render_template("admin/settings.html")

@app.route("/delete-user/<int:id>")
@login_required
def delete_user(id):
    if current_user.role != "admin": return redirect("/dashboard")
    user = User.query.get_or_404(id)
    if user.role == "admin":
        flash("Admin tidak bisa dihapus", "error")
        return redirect("/admin/users")
    db.session.delete(user)
    db.session.commit()
    flash("User berhasil dihapus", "success")
    return redirect("/admin/users")

@app.route("/add-product", methods=["POST"])
@login_required
def add_product():
    if current_user.role != "admin": return redirect("/")
    name  = request.form["name"]
    price = request.form["price"]
    stock = request.form["stock"]
    image_file = request.files["image"]
    filename = ""
    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        image_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    db.session.add(Product(name=name, price=price, stock=stock, image=filename))
    db.session.commit()
    flash("Produk berhasil ditambahkan", "success")
    return redirect("/admin")

@app.route("/delete-product/<int:id>")
@login_required
def delete_product(id):
    if current_user.role != "admin": return redirect("/")
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash("Produk berhasil dihapus", "success")
    return redirect("/admin")

@app.route("/edit-product/<int:id>", methods=["GET", "POST"])
@login_required
def edit_product(id):
    if current_user.role != "admin": return redirect("/")
    product = Product.query.get_or_404(id)
    if request.method == "POST":
        product.name  = request.form["name"]
        product.price = request.form["price"]
        product.stock = request.form["stock"]
        db.session.commit()
        flash("Produk berhasil diupdate", "success")
        return redirect("/admin")
    return render_template("admin/edit_product.html", product=product)


# ── RUN ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email="admin@gmail.com").first():
            db.session.add(User(
                username="Administrator",
                email="admin@gmail.com",
                password=generate_password_hash("admin123"),
                role="admin"
            ))
            db.session.commit()
    app.run(debug=True)