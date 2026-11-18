import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, func
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField,
    TextAreaField,
    SubmitField,
    RadioField,
    IntegerField,
    FloatField,
    SelectField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    Regexp,
    Email,
    Optional,
    NumberRange,
    ValidationError,
)

# ==========================================
# 1. CẤU HÌNH ỨNG DỤNG & DATABASE
# ==========================================
app = Flask(__name__)
app.secret_key = "mon_hoc_ma_nguon_mo_secret_key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///bookstore.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # Giới hạn request 4MB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


# ==========================================
# 2. CÁC BẢNG CƠ SỞ DỮ LIỆU (MODELS)
# ==========================================
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    books = db.relationship("Book", backref="category", lazy=True)


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(200))
    publisher = db.Column(db.String(200))
    year = db.Column(db.Integer)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    image = db.Column(db.String(200))
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    order_items = db.relationship("OrderItem", backref="book", lazy=True)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    address = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text)
    payment_method = db.Column(db.String(50), default="cash")
    total_amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(50), default="Chờ xác nhận")
    created_at = db.Column(db.DateTime, default=datetime.now)
    shipping_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    items = db.relationship(
        "OrderItem", backref="order", lazy=True, cascade="all, delete-orphan"
    )


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey("book.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)


# Truyền số đơn "Chờ xác nhận" cho thanh menu trái của Admin
@app.context_processor
def inject_admin_badges():
    try:
        pending_count = Order.query.filter_by(status="Chờ xác nhận").count()
    except Exception:
        pending_count = 0
    return dict(pending_orders_badge=pending_count)


# ==========================================
# 3. CÁC BIỂU MẪU (FLASK-WTF FORMS)
# ==========================================
class CheckoutForm(FlaskForm):
    customer_name = StringField(
        "Họ tên", validators=[DataRequired(message="Bắt buộc nhập họ tên")]
    )
    phone = StringField(
        "Số điện thoại",
        validators=[
            DataRequired(message="Bắt buộc nhập SĐT"),
            Length(min=10, max=10, message="Số điện thoại gồm 10 chữ số."),
            Regexp(r"^0[0-9]{9}$", message="SĐT phải bắt đầu bằng 0 và gồm 10 chữ số."),
        ],
    )
    email = StringField(
        "Email", validators=[Optional(), Email(message="Email không đúng định dạng")]
    )
    address = StringField(
        "Địa chỉ giao hàng", validators=[DataRequired(message="Bắt buộc nhập địa chỉ")]
    )
    notes = TextAreaField("Ghi chú")
    payment_method = RadioField(
        "Thanh toán",
        choices=[("cash", "Tiền mặt khi nhận hàng"), ("transfer", "Chuyển khoản")],
        default="cash",
    )
    submit = SubmitField("Xác nhận đặt hàng")


class BookForm(FlaskForm):
    title = StringField(
        "Tên sách", validators=[DataRequired(message="Bắt buộc nhập tên sách")]
    )
    author = StringField(
        "Tác giả", validators=[DataRequired(message="Bắt buộc nhập tác giả")]
    )
    category_id = SelectField(
        "Danh mục", coerce=int, validators=[DataRequired(message="Chọn danh mục")]
    )
    year = IntegerField("Năm xuất bản", validators=[Optional()])
    price = FloatField(
        "Giá (đồng)",
        validators=[
            DataRequired(message="Bắt buộc nhập giá"),
            NumberRange(min=1000, message="Giá phải từ 1.000 đ trở lên."),
        ],
    )
    stock = IntegerField(
        "Tồn kho",
        validators=[
            DataRequired(message="Bắt buộc nhập tồn kho"),
            NumberRange(min=0, message="Tồn kho không âm."),
        ],
    )
    description = TextAreaField("Mô tả", validators=[Optional()])
    image = FileField(
        "Ảnh bìa",
        validators=[
            Optional(),
            FileAllowed(
                ["jpg", "jpeg", "png", "webp"], "Chỉ chấp nhận ảnh JPG, PNG, WEBP!"
            ),
        ],
    )
    submit = SubmitField("Lưu")

    def __init__(self, book_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.book_id = book_id

    def validate_title(self, field):
        title_clean = field.data.strip()
        query = Book.query.filter(func.lower(Book.title) == title_clean.lower())
        if self.book_id:
            query = query.filter(Book.id != self.book_id)
        if query.first():
            raise ValidationError("Tên sách đã tồn tại.")

    def validate_year(self, field):
        if field.data is not None:
            current_year = datetime.now().year
            if field.data < 1900 or field.data > current_year:
                raise ValidationError(f"Năm xuất bản phải từ 1900 đến {current_year}.")

    def validate_image(self, field):
        if field.data and hasattr(field.data, "filename") and field.data.filename:
            field.data.seek(0, os.SEEK_END)
            file_size = field.data.tell()
            field.data.seek(0)
            if file_size > 2 * 1024 * 1024:
                raise ValidationError("Kích thước ảnh tối đa là 2 MB.")


class CategoryForm(FlaskForm):
    name = StringField(
        "Tên", validators=[DataRequired(message="Bắt buộc nhập tên danh mục")]
    )
    description = TextAreaField("Mô tả", validators=[Optional()])
    submit = SubmitField("Lưu")

    def __init__(self, category_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_id = category_id

    def validate_name(self, field):
        name_clean = field.data.strip()
        query = Category.query.filter(func.lower(Category.name) == name_clean.lower())
        if self.category_id:
            query = query.filter(Category.id != self.category_id)
        if query.first():
            raise ValidationError("Danh mục đã tồn tại.")


class EmptyForm(FlaskForm):
    pass


# ==========================================
# 4. ROUTES KHÁCH HÀNG
# ==========================================
@app.route("/")
@app.route("/books")
def books():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", "").strip()

    query = Book.query
    if q:
        query = query.filter(or_(Book.title.contains(q), Book.author.contains(q)))
    if category_id and category_id.isdigit():
        query = query.filter(Book.category_id == int(category_id))

    books_list = query.order_by(Book.id.desc()).all()
    categories = Category.query.all()
    return render_template("books.html", books=books_list, categories=categories)


@app.route("/books/<int:id>")
@app.route("/book/<int:id>")
def book_detail(id):
    book = Book.query.get_or_404(id)
    return render_template("book_detail.html", book=book)


# ==========================================
# 5. ROUTES GIỎ HÀNG
# ==========================================
@app.route("/cart")
def cart():
    cart_session = session.get("cart", {})
    cart_items = []
    total_amount = 0

    for book_id, qty in cart_session.items():
        book = Book.query.get(int(book_id))
        if book:
            subtotal = book.price * qty
            total_amount += subtotal
            cart_items.append({"book": book, "quantity": qty, "subtotal": subtotal})

    return render_template(
        "cart.html", cart_items=cart_items, total_amount=total_amount
    )


@app.route("/cart/add/<int:book_id>", methods=["POST"])
def add_to_cart(book_id):
    book = Book.query.get_or_404(book_id)
    cart = session.get("cart", {})
    book_id_str = str(book_id)

    try:
        quantity = int(request.form.get("quantity", 1))
    except ValueError:
        quantity = 1

    current_qty = cart.get(book_id_str, 0)
    if quantity < 1 or current_qty + quantity > book.stock:
        flash("Số lượng không hợp lệ hoặc vượt quá tồn kho!", "danger")
        return redirect(request.referrer or url_for("books"))

    cart[book_id_str] = current_qty + quantity
    session["cart"] = cart
    session.modified = True
    flash(f"Đã thêm {quantity} × {book.title} vào giỏ hàng.", "success")
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/update/<int:book_id>", methods=["POST"])
def update_cart(book_id):
    cart = session.get("cart", {})
    book_id_str = str(book_id)

    if book_id_str in cart:
        action = request.form.get("action")
        book = Book.query.get(book_id)

        if book and action == "increase" and cart[book_id_str] < book.stock:
            cart[book_id_str] += 1
        elif action == "decrease":
            cart[book_id_str] -= 1
            if cart[book_id_str] <= 0:
                cart.pop(book_id_str)

        session["cart"] = cart
        session.modified = True

    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:book_id>", methods=["POST"])
def remove_from_cart(book_id):
    cart = session.get("cart", {})
    book_id_str = str(book_id)

    if book_id_str in cart:
        cart.pop(book_id_str)
        session["cart"] = cart
        session.modified = True
        flash("Đã xoá sách khỏi giỏ hàng.", "success")

    return redirect(url_for("cart"))


@app.route("/cart/clear", methods=["POST"])
def clear_cart():
    session.pop("cart", None)
    flash("Đã xoá toàn bộ giỏ hàng.", "success")
    return redirect(url_for("cart"))


# ==========================================
# 6. THANH TOÁN & CHI TIẾT ĐƠN HÀNG KHÁCH
# ==========================================
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_session = session.get("cart", {})
    if not cart_session:
        flash("Giỏ hàng trống, vui lòng chọn sách trước khi đặt hàng.", "warning")
        return redirect(url_for("cart"))

    cart_items = []
    subtotal = 0

    for book_id, qty in cart_session.items():
        book = Book.query.get(int(book_id))
        if book:
            item_subtotal = book.price * qty
            subtotal += item_subtotal
            cart_items.append(
                {"book": book, "quantity": qty, "subtotal": item_subtotal}
            )

    shipping_fee = 0 if subtotal >= 200000 else 20000
    total = subtotal + shipping_fee

    form = CheckoutForm()

    if form.validate_on_submit():
        for item in cart_items:
            if item["quantity"] > item["book"].stock:
                flash(
                    f"Sách '{item['book'].title}' không đủ hàng (chỉ còn {item['book'].stock}).",
                    "danger",
                )
                return redirect(url_for("cart"))

        order = Order(
            customer_name=form.customer_name.data,
            phone=form.phone.data,
            email=form.email.data,
            address=form.address.data,
            notes=form.notes.data,
            payment_method=form.payment_method.data,
            total_amount=total,
            status="Chờ xác nhận",
            created_at=datetime.now(),
        )
        db.session.add(order)
        db.session.flush()

        for item in cart_items:
            order_item = OrderItem(
                order_id=order.id,
                book_id=item["book"].id,
                quantity=item["quantity"],
                price=item["book"].price,
            )
            db.session.add(order_item)
            item["book"].stock -= item["quantity"]

        db.session.commit()
        session.pop("cart", None)
        flash("Đặt hàng thành công!", "success")
        return redirect(url_for("order_detail", id=order.id))

    return render_template(
        "checkout.html",
        form=form,
        cart_items=cart_items,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
    )


@app.route("/orders/<int:id>")
def order_detail(id):
    order = Order.query.get_or_404(id)
    subtotal = sum(item.price * item.quantity for item in order.items)
    shipping_fee = 0 if subtotal >= 200000 else 20000
    return render_template(
        "order_detail.html", order=order, subtotal=subtotal, shipping_fee=shipping_fee
    )


# ==========================================
# 7. ROUTES QUẢN TRỊ (ADMIN - MÀN HÌNH 6 -> 11)
# ==========================================
@app.route("/admin")
def admin_dashboard():
    total_books = Book.query.count()
    total_categories = Category.query.count()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status="Chờ xác nhận").count()
    total_revenue = (
        db.session.query(func.sum(Order.total_amount))
        .filter(Order.status != "Đã huỷ")
        .scalar()
        or 0
    )
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    low_stock_books = Book.query.filter(Book.stock <= 5).all()

    return render_template(
        "dashboard.html",
        total_books=total_books,
        book_count=total_books,
        total_categories=total_categories,
        category_count=total_categories,
        total_orders=total_orders,
        order_count=total_orders,
        pending_orders=pending_orders,
        revenue=total_revenue,
        total_revenue=total_revenue,
        recent_orders=recent_orders,
        orders=recent_orders,
        low_stock_books=low_stock_books,
    )


# --- MÀN HÌNH 7: QUẢN LÝ SÁCH (/admin/books) ---
@app.route("/admin/books")
def admin_books():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", "").strip()
    stock_filter = request.args.get("stock", "").strip()
    page = request.args.get("page", 1, type=int)

    query = Book.query
    if q:
        query = query.filter(
            or_(Book.title.ilike(f"%{q}%"), Book.author.ilike(f"%{q}%"))
        )
    if category_id and category_id.isdigit():
        query = query.filter(Book.category_id == int(category_id))
    if stock_filter == "available":
        query = query.filter(Book.stock > 0)
    elif stock_filter == "low":
        query = query.filter(Book.stock > 0, Book.stock <= 5)
    elif stock_filter == "out":
        query = query.filter(Book.stock == 0)

    total_filtered = query.count()
    pagination = query.order_by(Book.id.desc()).paginate(
        page=page, per_page=5, error_out=False
    )
    categories = Category.query.order_by(Category.name.asc()).all()
    csrf_form = EmptyForm()

    return render_template(
        "admin_books.html",
        books=pagination.items,
        pagination=pagination,
        total_filtered=total_filtered,
        categories=categories,
        q=q,
        selected_category=category_id,
        selected_stock=stock_filter,
        csrf_form=csrf_form,
    )


# --- MÀN HÌNH 8: THÊM & SỬA SÁCH ---
def save_book_image(file_storage, old_filename=None):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return old_filename
    ext = os.path.splitext(file_storage.filename)[1].lower()
    new_filename = f"{uuid.uuid4().hex}{ext}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], new_filename))

    # Xoá ảnh cũ nếu có
    if old_filename:
        old_path = os.path.join(app.config["UPLOAD_FOLDER"], old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
    return new_filename


@app.route("/admin/books/new", methods=["GET", "POST"])
def new_book():
    form = BookForm()
    form.category_id.choices = [
        (c.id, c.name) for c in Category.query.order_by(Category.name.asc()).all()
    ]

    if form.validate_on_submit():
        filename = save_book_image(form.image.data)
        book = Book(
            title=form.title.data.strip(),
            author=form.author.data.strip(),
            category_id=form.category_id.data,
            year=form.year.data,
            price=form.price.data,
            stock=form.stock.data,
            description=form.description.data,
            image=filename,
        )
        db.session.add(book)
        db.session.commit()
        flash(f'Đã thêm sách "{book.title}".', "success")
        return redirect(url_for("admin_books"))

    return render_template("book_form.html", form=form, book=None)


@app.route("/admin/books/<int:id>/edit", methods=["GET", "POST"])
def edit_book(id):
    book = Book.query.get_or_404(id)
    form = BookForm(book_id=book.id, obj=book)
    form.category_id.choices = [
        (c.id, c.name) for c in Category.query.order_by(Category.name.asc()).all()
    ]

    if form.validate_on_submit():
        book.title = form.title.data.strip()
        book.author = form.author.data.strip()
        book.category_id = form.category_id.data
        book.year = form.year.data
        book.price = form.price.data
        book.stock = form.stock.data
        book.description = form.description.data
        book.image = save_book_image(form.image.data, old_filename=book.image)

        db.session.commit()
        flash(f'Đã cập nhật sách "{book.title}".', "success")
        return redirect(url_for("admin_books"))

    return render_template("book_form.html", form=form, book=book)


@app.route("/admin/books/<int:id>/delete", methods=["POST"])
def delete_book(id):
    book = Book.query.get_or_404(id)
    if book.order_items:
        flash(f'Không thể xoá "{book.title}": sách đã có trong đơn hàng.', "danger")
        return redirect(url_for("admin_books"))

    if book.image:
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], book.image)
        if os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass

    db.session.delete(book)
    db.session.commit()
    flash(f'Đã xoá sách "{book.title}".', "success")
    return redirect(url_for("admin_books"))


# --- MÀN HÌNH 9: DANH MỤC SÁCH (/admin/categories) ---
@app.route("/admin/categories", methods=["GET", "POST"])
def admin_categories():
    edit_id = request.args.get("edit", type=int) or request.form.get(
        "edit_id", type=int
    )
    edit_cat = Category.query.get(edit_id) if edit_id else None

    form = CategoryForm(category_id=edit_cat.id if edit_cat else None, obj=edit_cat)

    if form.validate_on_submit():
        if edit_cat:
            edit_cat.name = form.name.data.strip()
            edit_cat.description = form.description.data
            db.session.commit()
            flash(f'Đã cập nhật danh mục "{edit_cat.name}".', "success")
        else:
            new_cat = Category(
                name=form.name.data.strip(), description=form.description.data
            )
            db.session.add(new_cat)
            db.session.commit()
            flash(f'Đã thêm danh mục "{new_cat.name}".', "success")
        return redirect(url_for("admin_categories"))

    # Một truy vấn group_by lấy tên và số sách kể cả danh mục chưa có sách
    categories_data = (
        db.session.query(Category, func.count(Book.id).label("book_count"))
        .outerjoin(Book, Category.id == Book.category_id)
        .group_by(Category.id)
        .order_by(Category.id.asc())
        .all()
    )
    csrf_form = EmptyForm()

    return render_template(
        "admin_categories.html",
        categories_data=categories_data,
        form=form,
        edit_cat=edit_cat,
        csrf_form=csrf_form,
    )


@app.route("/admin/categories/<int:id>/delete", methods=["POST"])
def delete_category(id):
    cat = Category.query.get_or_404(id)
    book_count = Book.query.filter_by(category_id=cat.id).count()
    if book_count > 0:
        flash(f'Không thể xoá "{cat.name}": còn {book_count} sách.', "danger")
    else:
        db.session.delete(cat)
        db.session.commit()
        flash(f'Đã xoá danh mục "{cat.name}".', "success")
    return redirect(url_for("admin_categories"))


# --- MÀN HÌNH 10: DANH SÁCH ĐƠN HÀNG (/admin/orders) ---
@app.route("/admin/orders")
def admin_orders():
    status_filter = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)

    # Một truy vấn group_by đếm số đơn theo từng trạng thái
    status_rows = (
        db.session.query(Order.status, func.count(Order.id))
        .group_by(Order.status)
        .all()
    )
    status_counts = dict(status_rows)
    total_all_orders = sum(status_counts.values())

    query = Order.query
    if status_filter:
        query = query.filter(Order.status == status_filter)
    if q:
        q_clean = q.lstrip("#").strip()
        conditions = [Order.customer_name.ilike(f"%{q}%"), Order.phone.ilike(f"%{q}%")]
        if q_clean.isdigit():
            conditions.append(Order.id == int(q_clean))
        query = query.filter(or_(*conditions))

    filtered_count = query.count()
    filtered_total_value = (
        query.with_entities(func.coalesce(func.sum(Order.total_amount), 0)).scalar()
        or 0
    )

    pagination = query.order_by(Order.created_at.desc(), Order.id.desc()).paginate(
        page=page, per_page=10, error_out=False
    )

    return render_template(
        "admin_orders.html",
        orders=pagination.items,
        pagination=pagination,
        status_filter=status_filter,
        q=q,
        status_counts=status_counts,
        total_all_orders=total_all_orders,
        filtered_count=filtered_count,
        filtered_total_value=filtered_total_value,
    )


# --- MÀN HÌNH 11: CHI TIẾT ĐƠN HÀNG (/admin/orders/<id>) ---
VALID_TRANSITIONS = {
    "Chờ xác nhận": ["Đang giao"],
    "Đang giao": ["Hoàn tất"],
    "Hoàn tất": [],
    "Đã huỷ": [],
}


@app.route("/admin/orders/<int:id>")
def admin_order_detail(id):
    order = Order.query.get_or_404(id)
    subtotal = sum(item.price * item.quantity for item in order.items)
    shipping_fee = 0 if subtotal >= 200000 else 20000
    next_statuses = VALID_TRANSITIONS.get(order.status, [])
    can_cancel = order.status in ["Chờ xác nhận", "Đang giao"]
    csrf_form = EmptyForm()

    return render_template(
        "admin_order_detail.html",
        order=order,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        next_statuses=next_statuses,
        can_cancel=can_cancel,
        csrf_form=csrf_form,
    )


@app.route("/admin/orders/<int:id>/status", methods=["POST"])
def update_order_status(id):
    order = Order.query.get_or_404(id)
    new_status = request.form.get("status", "").strip()

    if order.status in ["Hoàn tất", "Đã huỷ"]:
        flash("Đơn hàng đã kết thúc, không thể thay đổi trạng thái.", "danger")
        return redirect(url_for("admin_order_detail", id=order.id))

    allowed = VALID_TRANSITIONS.get(order.status, []) + (
        ["Đã huỷ"] if order.status in ["Chờ xác nhận", "Đang giao"] else []
    )
    if new_status not in allowed:
        flash(
            f'Chuyển trạng thái từ "{order.status}" sang "{new_status}" không hợp lệ!',
            "danger",
        )
        return redirect(url_for("admin_order_detail", id=order.id))

    now = datetime.now()
    if new_status == "Đang giao":
        order.shipping_at = now
    elif new_status == "Hoàn tất":
        order.completed_at = now
    elif new_status == "Đã huỷ":
        order.cancelled_at = now
        # Hoàn lại tồn kho các sách trong đơn
        for item in order.items:
            if item.book:
                item.book.stock += item.quantity

    order.status = new_status
    db.session.commit()
    flash(f'Đã cập nhật trạng thái đơn #{order.id} thành "{new_status}".', "success")
    return redirect(url_for("admin_order_detail", id=order.id))


# ==========================================
# 8. CHẠY ỨNG DỤNG & TỰ ĐỘNG NÂNG CẤP CỘT DB
# ==========================================
def ensure_columns():
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    if "category" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("category")]
        if "description" not in cols:
            db.session.execute(text("ALTER TABLE category ADD COLUMN description TEXT"))
    if "order" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("order")]
        for col_name in ["shipping_at", "completed_at", "cancelled_at"]:
            if col_name not in cols:
                db.session.execute(
                    text(f'ALTER TABLE "order" ADD COLUMN {col_name} DATETIME')
                )
    db.session.commit()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_columns()
    app.run(debug=True)
