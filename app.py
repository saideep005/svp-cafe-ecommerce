from flask import Flask, render_template, request, redirect, session, flash, g
import pymysql
pymysql.install_as_MySQLdb()
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
import random
import string
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from flask import send_file
import os
import socket


app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "svp_cafe_secret_key"
)

# =========================
# MYSQL CONFIGURATION
# =========================


app.config["MYSQL_HOST"] = os.environ.get("MYSQL_HOST")
app.config["MYSQL_PORT"] = int(os.environ.get("MYSQL_PORT", 4000))
app.config["MYSQL_USER"] = os.environ.get("MYSQL_USER")
app.config["MYSQL_PASSWORD"] = os.environ.get("MYSQL_PASSWORD")
app.config["MYSQL_DB"] = os.environ.get("MYSQL_DB")

app.config["MYSQL_CUSTOM_OPTIONS"] = {
    "ssl_mode": "REQUIRED",
    "ssl": {
        "ca": os.path.join(os.path.dirname(__file__), "ca.pem")
    }
}

class MySQLCompat:
    @property
    def connection(self):
        if "db" not in g:
            g.db = pymysql.connect(
               host="75.2.106.174",
                port=app.config["MYSQL_PORT"],
                user=app.config["MYSQL_USER"],
                password=app.config["MYSQL_PASSWORD"],
                database=app.config["MYSQL_DB"],
                ssl_verify_cert=True,
                ssl_verify_identity=False,
                ssl_ca=os.path.join(os.path.dirname(__file__), "ca.pem")
            )
        return g.db


mysql = MySQLCompat()


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# =========================
# EMAIL CONFIGURATION
# =========================

app.config["MAIL_SERVER"] = "smtp.gmail.com"

app.config["MAIL_PORT"] = 587

app.config["MAIL_USE_TLS"] = True

app.config["MAIL_USERNAME"] = os.environ.get(
    "MAIL_USERNAME"
)

app.config["MAIL_PASSWORD"] = os.environ.get(
    "MAIL_PASSWORD"
)

app.config["MAIL_DEFAULT_SENDER"] = app.config["MAIL_USERNAME"]

mail = Mail(app)

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]

        cur = mysql.connection.cursor()

        cur.execute(
            """
            SELECT username, password
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        user = cur.fetchone()

        cur.close()

        if user is None:
            return "Invalid Username or Password"

        stored_password = user[1]

        try:
            password_correct = check_password_hash(
                stored_password,
                password
            )
        except Exception:
            password_correct = False

        if password_correct:

            session["username"] = user[0]

            return redirect("/menu")

        return "Invalid Username or Password"

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        fullname = request.form["fullname"]
        email = request.form["email"]
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            return "Passwords do not match!"
        hashed_password = generate_password_hash(password)

        cur = mysql.connection.cursor()

        cur.execute("""
INSERT INTO users(fullname, email, username, password)
VALUES(%s, %s, %s, %s)
""", (fullname, email, username, hashed_password))

        mysql.connection.commit()
        cur.close()

        return redirect("/login")

    return render_template("register.html")

@app.route("/menu")
def menu():

    search = request.args.get("search", "")
    category = request.args.get("category", "All")

    cur = mysql.connection.cursor()


    # =========================
    # GET PRODUCTS
    # =========================

    query = "SELECT * FROM products WHERE 1=1"

    values = []


    if search:

        query += " AND product_name LIKE %s"

        values.append("%" + search + "%")


    if category != "All":

        query += " AND category=%s"

        values.append(category)


    cur.execute(
        query,
        tuple(values)
    )

    products = cur.fetchall()

    print("CATEGORY:", category)
    print("PRODUCT COUNT:", len(products))



    # =========================
    # GET ACTIVE COUPONS
    # =========================

    cur.execute("""
        SELECT
            coupon_code,
            discount_percent,
            expiry_date
        FROM coupons
        WHERE status='Active'
        AND (
            expiry_date IS NULL
            OR expiry_date >= CURDATE()
        )
        ORDER BY id DESC
    """)

    coupons = cur.fetchall()


    cur.close()


    return render_template(
        "menu.html",
        products=products,
        search=search,
        category=category,
        coupons=coupons
    )

@app.route("/product/<int:product_id>")
def product_details(product_id):

    cur = mysql.connection.cursor()

    # Fetch product details
    cur.execute(
        "SELECT * FROM products WHERE id=%s",
        (product_id,)
    )

    product = cur.fetchone()

    # Fetch reviews for this product
    cur.execute("""
        SELECT username, rating, review, created_at
        FROM reviews
        WHERE product_id = %s
        ORDER BY created_at DESC
    """, (product_id,))

    reviews = cur.fetchall()

    cur.close()

    return render_template(
        "product_details.html",
        product=product,
        reviews=reviews
    )

@app.route("/add_to_wishlist/<int:product_id>")
def add_to_wishlist(product_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    # Check if the product is already in the wishlist
    cur.execute(
        "SELECT * FROM wishlist WHERE username=%s AND product_id=%s",
        (username, product_id)
    )

    item = cur.fetchone()

    if not item:
        cur.execute(
            """
            INSERT INTO wishlist(username, product_id)
            VALUES(%s, %s)
            """,
            (username, product_id)
        )

        mysql.connection.commit()

    cur.close()

    return redirect("/wishlist")

@app.route("/wishlist")
def wishlist():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT products.id,
               products.product_name,
               products.price,
               products.image,
               products.category,
               products.stock
        FROM wishlist
        JOIN products
        ON wishlist.product_id = products.id
        WHERE wishlist.username=%s
    """, (username,))

    wishlist_items = cur.fetchall()

    cur.close()

    return render_template(
        "wishlist.html",
        wishlist_items=wishlist_items
    )

@app.route("/remove_from_wishlist/<int:product_id>")
def remove_from_wishlist(product_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    cur.execute(
        """
        DELETE FROM wishlist
        WHERE username=%s AND product_id=%s
        """,
        (username, product_id)
    )

    mysql.connection.commit()

    cur.close()

    return redirect("/wishlist")

@app.route("/add_to_cart/<int:product_id>")
def add_to_cart(product_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    # Get available stock
    cur.execute(
        "SELECT stock FROM products WHERE id=%s",
        (product_id,)
    )

    product = cur.fetchone()

    if product is None:
        cur.close()
        return redirect("/menu")

    stock = product[0]

    if stock <= 0:
        cur.close()
        return redirect("/menu")

    # Check if product already exists in cart
    cur.execute(
        """
        SELECT quantity
        FROM cart
        WHERE username=%s AND product_id=%s
        """,
        (username, product_id)
    )

    item = cur.fetchone()

    if item:

        cart_quantity = item[0]

        # Do not allow quantity more than stock
        if cart_quantity >= stock:
            flash(f"⚠ Only {stock} item(s) available in stock.", "warning")
            cur.close()
            return redirect("/menu")

        cur.execute(
            """
            UPDATE cart
            SET quantity = quantity + 1
            WHERE username=%s AND product_id=%s
            """,
            (username, product_id)
        )

    else:

        cur.execute(
            """
            INSERT INTO cart(username, product_id, quantity)
            VALUES(%s,%s,%s)
            """,
            (username, product_id, 1)
        )

    mysql.connection.commit()
    cur.close()

    return redirect("/cart")

@app.route("/cart")
def cart():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    cur.execute("""
    SELECT products.id,
           products.product_name,
           products.price,
           products.image,
           cart.quantity
    FROM cart
    JOIN products
    ON cart.product_id = products.id
    WHERE cart.username=%s
""", (username,))   

    cart_items = cur.fetchall()

    total = 0

    for item in cart_items:
        total += item[2] * item[4]

    cur.close()

    return render_template(
        "cart.html",
        cart_items=cart_items,
        total=total
    )
@app.route("/remove_from_cart/<int:product_id>")
def remove_from_cart(product_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    cur.execute(
        "DELETE FROM cart WHERE username=%s AND product_id=%s",
        (username, product_id)
    )

    mysql.connection.commit()
    cur.close()

    return redirect("/cart")


# 👇 PASTE THE NEW CODE HERE

@app.route("/increase_quantity/<int:product_id>")
def increase_quantity(product_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    # Get current cart quantity
    cur.execute("""
        SELECT quantity
        FROM cart
        WHERE username=%s AND product_id=%s
    """, (username, product_id))

    cart_item = cur.fetchone()

    if not cart_item:
        cur.close()
        return redirect("/cart")

    cart_quantity = cart_item[0]

    # Get available stock
    cur.execute("""
        SELECT stock
        FROM products
        WHERE id=%s
    """, (product_id,))

    stock = cur.fetchone()[0]

    # Do not allow quantity to exceed stock
    if cart_quantity >= stock:
        flash(f"⚠ Only {stock} item(s) available in stock.", "warning")
        cur.close()
        return redirect("/cart")

    # Increase quantity
    cur.execute("""
        UPDATE cart
        SET quantity = quantity + 1
        WHERE username=%s AND product_id=%s
    """, (username, product_id))

    mysql.connection.commit()
    cur.close()

    return redirect("/cart")


@app.route("/decrease_quantity/<int:product_id>")
def decrease_quantity(product_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT quantity
        FROM cart
        WHERE username=%s AND product_id=%s
    """, (username, product_id))

    item = cur.fetchone()

    if item:

        if item[0] > 1:

            cur.execute("""
                UPDATE cart
                SET quantity = quantity - 1
                WHERE username=%s AND product_id=%s
            """, (username, product_id))

        else:

            cur.execute("""
                DELETE FROM cart
                WHERE username=%s AND product_id=%s
            """, (username, product_id))

    mysql.connection.commit()
    cur.close()

    return redirect("/cart")


# 👇 KEEP YOUR CHECKOUT ROUTE BELOW
@app.route("/checkout", methods=["GET", "POST"])
def checkout():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    # Calculate total amount
    cur.execute("""
        SELECT products.price, cart.quantity
        FROM cart
        JOIN products
        ON cart.product_id = products.id
        WHERE cart.username=%s
    """, (username,))

    cart_items = cur.fetchall()

    total = 0

    for item in cart_items:
        total += float(item[0]) * item[1]

    if request.method == "POST":

        customer_name = request.form["customer_name"]
        phone = request.form["phone"]
        address = request.form["address"]
        payment_method = request.form["payment_method"]
        coupon = request.form["coupon"].strip().upper()

        # --------------------------------
        # APPLY COUPON
        # --------------------------------

        if coupon:

            cur.execute("""
                SELECT
                    discount_percent,
                    expiry_date,
                    status
                FROM coupons
                WHERE coupon_code=%s
            """, (coupon,))

            coupon_data = cur.fetchone()

            if not coupon_data:

                cur.close()
                return "Invalid Coupon Code!"

            discount = coupon_data[0]
            expiry_date = coupon_data[1]
            coupon_status = coupon_data[2]

            # Check coupon status
            if coupon_status != "Active":

                cur.close()
                return "Coupon is inactive!"

            # Check expiry date
            if expiry_date is not None:

                cur.execute("""
                    SELECT CURDATE()
                """)

                today = cur.fetchone()[0]

                if expiry_date < today:

                    # Automatically deactivate expired coupon
                    cur.execute("""
                        UPDATE coupons
                        SET status='Inactive'
                        WHERE coupon_code=%s
                    """, (coupon,))

                    mysql.connection.commit()

                    cur.close()

                    return "Coupon has expired!"

            # Apply discount
            total = total - (total * float(discount) / 100)


        # --------------------------------
        # GET CUSTOMER EMAIL
        # --------------------------------

        cur.execute("""
            SELECT email
            FROM users
            WHERE username=%s
        """, (username,))

        user_data = cur.fetchone()

        if not user_data:

            cur.close()
            return "Customer email not found!"

        customer_email = user_data[0]


        # --------------------------------
        # INSERT ORDER
        # --------------------------------

        cur.execute("""
            INSERT INTO orders
            (username, customer_name, phone, address, payment_method, total)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            username,
            customer_name,
            phone,
            address,
            payment_method,
            total
        ))

        order_id = cur.lastrowid


        # --------------------------------
        # GET ALL PRODUCTS IN CART
        # --------------------------------

        cur.execute("""
            SELECT
                products.id,
                products.product_name,
                products.price,
                cart.quantity
            FROM cart
            JOIN products
            ON cart.product_id = products.id
            WHERE cart.username=%s
        """, (username,))

        cart_products = cur.fetchall()


        # --------------------------------
        # INSERT ORDER ITEMS + REDUCE STOCK
        # --------------------------------

        for product in cart_products:

            product_id = product[0]
            product_name = product[1]
            price = product[2]
            quantity = product[3]

            subtotal = price * quantity

            # Insert order item
            cur.execute("""
                INSERT INTO order_items
                (order_id, product_id, product_name, price, quantity, subtotal)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                order_id,
                product_id,
                product_name,
                price,
                quantity,
                subtotal
            ))

            # Reduce stock
            cur.execute("""
                UPDATE products
                SET stock = stock - %s
                WHERE id=%s
            """, (
                quantity,
                product_id
            ))


        # --------------------------------
        # CLEAR CART
        # --------------------------------

        cur.execute(
            "DELETE FROM cart WHERE username=%s",
            (username,)
        )


        # Save order
        mysql.connection.commit()

        cur.close()


        # --------------------------------
        # SEND ORDER CONFIRMATION EMAIL
        # --------------------------------

        try:

            # Create product list for email
            product_details = ""

            for product in cart_products:

                product_name = product[1]
                price = float(product[2])
                quantity = product[3]
                subtotal = price * quantity

                product_details += (
                    f"{product_name} x {quantity} "
                    f"= ₹{subtotal:.2f}\n"
                )


            msg = Message(
                subject=f"☕ SVP Cafe - Order Confirmation #{order_id}",
                recipients=[customer_email]
            )

            msg.body = f"""
Hello {customer_name},

Thank you for ordering from SVP Cafe! ☕

Your order has been successfully placed.

----------------------------------------
ORDER DETAILS
----------------------------------------

Order ID       : {order_id}

Customer Name  : {customer_name}

Phone          : {phone}

Payment Method : {payment_method}

Order Status   : Pending

----------------------------------------
ORDER ITEMS
----------------------------------------

{product_details}
----------------------------------------

Total Amount   : ₹{total:.2f}

Delivery Address:
{address}

----------------------------------------

Your order has been received successfully.
We will start preparing your order shortly.

Thank you for choosing SVP Cafe! ☕

SVP Cafe
"""

            mail.send(msg)

            print("Order confirmation email sent successfully.")

        except Exception as e:

            print("Email sending failed:", e)


        # --------------------------------
        # ORDER SUCCESS PAGE
        # --------------------------------

        return render_template(
            "order_success.html",
            total=total,
            order_id=order_id
        )


    cur.close()

    return render_template(
        "checkout.html",
        total=total
    )




@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        cur = mysql.connection.cursor()

        cur.execute(
            "SELECT * FROM admin WHERE username=%s AND password=%s",
            (username, password)
        )

        admin = cur.fetchone()

        cur.close()

        if admin:

            session["admin"] = username

            return redirect("/admin_dashboard")

        else:

            return "Invalid Admin Username or Password"

    return render_template("admin_login.html")


@app.route("/admin_dashboard")
def admin_dashboard():

    if "admin" not in session:
        return redirect("/admin_login")

    cur = mysql.connection.cursor()

    # Total Products
    cur.execute("SELECT COUNT(*) FROM products")
    total_products = cur.fetchone()[0]

    # Total Users
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    # Total Orders
    cur.execute("SELECT COUNT(*) FROM orders")
    total_orders = cur.fetchone()[0]

    # Total Revenue
    cur.execute("""
        SELECT COALESCE(SUM(total),0)
        FROM orders
        WHERE status!='Cancelled'
    """)
    revenue = cur.fetchone()[0]

    # Pending Orders
    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status='Pending'
    """)
    pending_orders = cur.fetchone()[0]

    # Delivered Orders
    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status='Delivered'
    """)
    delivered_orders = cur.fetchone()[0]

    # Cancelled Orders
    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status='Cancelled'
    """)
    cancelled_orders = cur.fetchone()[0]

    # Today's Sales
    cur.execute("""
        SELECT COALESCE(SUM(total),0)
        FROM orders
        WHERE DATE(order_date)=CURDATE()
        AND status!='Cancelled'
    """)
    today_sales = cur.fetchone()[0]

    # Weekly Sales
    cur.execute("""
        SELECT COALESCE(SUM(total),0)
        FROM orders
        WHERE YEARWEEK(order_date,1)=YEARWEEK(CURDATE(),1)
        AND status!='Cancelled'
    """)
    weekly_sales = cur.fetchone()[0]

    # Monthly Sales
    cur.execute("""
        SELECT COALESCE(SUM(total),0)
        FROM orders
        WHERE MONTH(order_date)=MONTH(CURDATE())
        AND YEAR(order_date)=YEAR(CURDATE())
        AND status!='Cancelled'
    """)
    monthly_sales = cur.fetchone()[0]

    # Top 5 Best Selling Products
    cur.execute("""
        SELECT
            product_name,
            SUM(quantity) AS total_sold
        FROM order_items
        GROUP BY product_name
        ORDER BY total_sold DESC
        LIMIT 5
    """)
    best_products = cur.fetchall()

    # Low Stock Products
    cur.execute("""
        SELECT
            id,
            product_name,
            stock
        FROM products
        WHERE stock<=5
        ORDER BY stock ASC
    """)
    low_stock = cur.fetchall()

    cur.close()

    return render_template(
        "admin_dashboard.html",
        total_products=total_products,
        total_users=total_users,
        total_orders=total_orders,
        revenue=revenue,
        pending_orders=pending_orders,
        delivered_orders=delivered_orders,
        cancelled_orders=cancelled_orders,
        today_sales=today_sales,
        weekly_sales=weekly_sales,
        monthly_sales=monthly_sales,
        best_products=best_products,
        low_stock=low_stock
    )

@app.route("/add_product", methods=["GET", "POST"])
def add_product():

    if "admin" not in session:
        return redirect("/admin_login")

    if request.method == "POST":

        product_name = request.form["product_name"]
        price = request.form["price"]
        stock = request.form["stock"]
        image = request.form["image"]

        cur = mysql.connection.cursor()

        cur.execute("""
            INSERT INTO products(product_name, price, stock, image)
            VALUES(%s, %s, %s, %s)
        """, (
            product_name,
            price,
            stock,
            image
        ))

        mysql.connection.commit()
        cur.close()

        return redirect("/admin_dashboard")

    return render_template("add_product.html")

@app.route("/view_products")
def view_products():

    if "admin" not in session:
        return redirect("/admin_login")

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM products")

    products = cur.fetchall()

    cur.close()

    return render_template(
        "view_products.html",
        products=products
    )

@app.route("/delete_product/<int:product_id>")
def delete_product(product_id):

    if "admin" not in session:
        return redirect("/admin_login")

    cur = mysql.connection.cursor()

    cur.execute(
        "DELETE FROM products WHERE id=%s",
        (product_id,)
    )

    mysql.connection.commit()
    cur.close()

    return redirect("/view_products")

@app.route("/edit_product/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):

    if "admin" not in session:
        return redirect("/admin_login")

    cur = mysql.connection.cursor()

    if request.method == "POST":

        product_name = request.form["product_name"]
        price = request.form["price"]
        stock = request.form["stock"]
        image = request.form["image"]

        cur.execute("""
            UPDATE products
            SET product_name=%s,
                price=%s,
                stock=%s,
                image=%s
            WHERE id=%s
        """, (
            product_name,
            price,
            stock,
            image,
            product_id
        ))

        mysql.connection.commit()
        cur.close()

        return redirect("/view_products")

    cur.execute(
        "SELECT * FROM products WHERE id=%s",
        (product_id,)
    )

    product = cur.fetchone()

    cur.close()

    return render_template(
        "edit_product.html",
        product=product
    )


@app.route("/view_orders")
def view_orders():

    if "admin" not in session:
        return redirect("/admin_login")

    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip()
    date_filter = request.args.get("date", "").strip()

    cur = mysql.connection.cursor()

    query = """
        SELECT
            orders.id,
            orders.username,
            GROUP_CONCAT(order_items.product_name SEPARATOR ', ') AS products,
            orders.customer_name,
            orders.phone,
            orders.address,
            orders.payment_method,
            orders.total,
            orders.order_date,
            orders.status
        FROM orders
        LEFT JOIN order_items
        ON orders.id = order_items.order_id
        WHERE 1=1
    """

    params = []

    # Search
    if search:

        query += """
            AND (
                CAST(orders.id AS CHAR) LIKE %s
                OR orders.username LIKE %s
                OR orders.customer_name LIKE %s
                OR orders.phone LIKE %s
                OR order_items.product_name LIKE %s
            )
        """

        search_value = "%" + search + "%"

        params.extend([
            search_value,
            search_value,
            search_value,
            search_value,
            search_value
        ])

    # Status filter
    if status_filter:

        query += """
            AND orders.status=%s
        """

        params.append(status_filter)

    # Date filter
    if date_filter:

        query += """
            AND DATE(orders.order_date)=%s
        """

        params.append(date_filter)

    query += """
        GROUP BY
            orders.id,
            orders.username,
            orders.customer_name,
            orders.phone,
            orders.address,
            orders.payment_method,
            orders.total,
            orders.order_date,
            orders.status

        ORDER BY orders.order_date DESC
    """

    cur.execute(query, params)

    orders = cur.fetchall()

    cur.close()

    return render_template(
        "view_orders.html",
        orders=orders,
        search=search,
        status_filter=status_filter,
        date_filter=date_filter
    )


@app.route("/view_users")
def view_users():

    if "admin" not in session:
        return redirect("/admin_login")

    search = request.args.get("search", "").strip()

    cur = mysql.connection.cursor()

    query = """
        SELECT
            id,
            fullname,
            email,
            username
        FROM users
        WHERE 1=1
    """

    params = []

    # Search by ID, name, email or username
    if search:

        query += """
            AND (
                CAST(id AS CHAR) LIKE %s
                OR fullname LIKE %s
                OR email LIKE %s
                OR username LIKE %s
            )
        """

        search_value = "%" + search + "%"

        params.extend([
            search_value,
            search_value,
            search_value,
            search_value
        ])

    query += """
        ORDER BY id DESC
    """

    cur.execute(query, params)

    users = cur.fetchall()

    cur.close()

    return render_template(
        "view_users.html",
        users=users,
        search=search
    )



@app.route("/logout")
def logout():

    session.pop("username", None)

    return redirect("/")


# 👇 ADD THE NEW ROUTE HERE

@app.route("/order_history")
def order_history():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    cur.execute("""
    SELECT
        orders.id,
        GROUP_CONCAT(order_items.product_name SEPARATOR ', ') AS products,
        orders.customer_name,
        orders.payment_method,
        orders.total,
        orders.order_date,
        orders.status
    FROM orders
    LEFT JOIN order_items
        ON orders.id = order_items.order_id
    WHERE orders.username=%s
    GROUP BY
        orders.id,
        orders.customer_name,
        orders.payment_method,
        orders.total,
        orders.order_date,
        orders.status
    ORDER BY orders.order_date DESC
""", (username,))

    orders = cur.fetchall()

    print(orders)
    
    cur.close()

    return render_template(
        "order_history.html",
        orders=orders
    )


@app.route("/profile")
def profile():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    cur.execute(
        """
        SELECT fullname,
               email,
               username,
               phone,
               address
        FROM users
        WHERE username=%s
        """,
        (username,)
    )

    user = cur.fetchone()

    cur.close()

    return render_template(
        "profile.html",
        user=user
    )


@app.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    if request.method == "POST":

        fullname = request.form["fullname"]
        email = request.form["email"]
        phone = request.form["phone"]
        address = request.form["address"]

        cur.execute("""
            UPDATE users
            SET fullname=%s,
                email=%s,
                phone=%s,
                address=%s
            WHERE username=%s
        """,
        (fullname, email, phone, address, username))

        mysql.connection.commit()

        cur.close()

        return redirect("/profile")

    cur.execute("""
        SELECT fullname,
               email,
               username,
               phone,
               address
        FROM users
        WHERE username=%s
    """,(username,))

    user = cur.fetchone()

    cur.close()

    return render_template(
        "edit_profile.html",
        user=user
    )

@app.route("/change_password", methods=["GET", "POST"])
def change_password():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    if request.method == "POST":

        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        cur = mysql.connection.cursor()

        cur.execute(
            "SELECT password FROM users WHERE username=%s",
            (username,)
        )

        stored_password = cur.fetchone()[0]

        if not check_password_hash(stored_password, current_password):
            cur.close()
            return "Current password is incorrect!"

        if new_password != confirm_password:
            cur.close()
            return "New passwords do not match!"

        new_hashed_password = generate_password_hash(new_password)

        cur.execute(
            "UPDATE users SET password=%s WHERE username=%s",
            (new_hashed_password, username)
        )

        mysql.connection.commit()

        cur.close()

        return redirect("/profile")

    return render_template("change_password.html")



@app.route("/admin_logout")
def admin_logout():

    session.pop("admin", None)

    return redirect("/admin_login")


@app.route("/test_mail")
def test_mail():

    msg = Message(
        "SVP Cafe Test Email",
        sender=app.config["MAIL_USERNAME"],
        recipients=[app.config["MAIL_USERNAME"]]
    )

    msg.body = "Congratulations! Flask-Mail is working successfully."

    mail.send(msg)

    return "Email Sent Successfully!"

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form["email"]

        cur = mysql.connection.cursor()

        cur.execute(
            "SELECT * FROM users WHERE email=%s",
            (email,)
        )

        user = cur.fetchone()

        cur.close()

        if not user:
            return "Email not found!"

        otp = str(random.randint(100000, 999999))

        session["otp"] = otp
        session["reset_email"] = email

        msg = Message(
            "SVP Cafe Password Reset OTP",
            sender=app.config["MAIL_USERNAME"],
            recipients=[email]
        )

        msg.body = f"Your OTP for password reset is: {otp}"

        mail.send(msg)

        return redirect("/verify_otp")

    return render_template("forgot_password.html")

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():

    if request.method == "POST":

        entered_otp = request.form["otp"]

        if entered_otp == session.get("otp"):

            return redirect("/reset_password")

        else:

            return "Invalid OTP!"

    return render_template("verify_otp.html")



@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():

    if request.method == "POST":

        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            return "Passwords do not match!"

        hashed_password = generate_password_hash(new_password)

        email = session.get("reset_email")

        cur = mysql.connection.cursor()

        cur.execute(
            "UPDATE users SET password=%s WHERE email=%s",
            (hashed_password, email)
        )

        mysql.connection.commit()

        cur.close()

        session.pop("otp", None)
        session.pop("reset_email", None)

        return redirect("/login")

    return render_template("reset_password.html")




@app.route("/review/<int:product_id>", methods=["GET", "POST"])
def review(product_id):

    if "username" not in session:
        return redirect("/login")

    if request.method == "POST":

        username = session["username"]
        rating = request.form["rating"]
        review = request.form["review"]

        cur = mysql.connection.cursor()

        cur.execute("""
            INSERT INTO reviews(username, product_id, rating, review)
            VALUES(%s, %s, %s, %s)
        """, (username, product_id, rating, review))

        mysql.connection.commit()
        cur.close()

        return "Review Submitted Successfully!"

    return render_template("review.html")


@app.route("/admin/reviews")
def admin_reviews():

    if "admin" not in session:
        return redirect("/admin_login")

    search = request.args.get("search", "").strip()
    rating_filter = request.args.get("rating", "").strip()

    cur = mysql.connection.cursor()

    query = """
        SELECT
            reviews.username,
            products.product_name,
            reviews.rating,
            reviews.review,
            reviews.created_at,
            reviews.id
        FROM reviews
        JOIN products
        ON reviews.product_id = products.id
        WHERE 1=1
    """

    params = []

    # Search username or product
    if search:

        query += """
            AND (
                reviews.username LIKE %s
                OR products.product_name LIKE %s
                OR reviews.review LIKE %s
            )
        """

        search_value = "%" + search + "%"

        params.extend([
            search_value,
            search_value,
            search_value
        ])

    # Rating filter
    if rating_filter:

        query += """
            AND reviews.rating=%s
        """

        params.append(rating_filter)

    query += """
        ORDER BY reviews.created_at DESC
    """

    cur.execute(query, params)

    reviews = cur.fetchall()

    cur.close()

    return render_template(
        "admin_reviews.html",
        reviews=reviews,
        search=search,
        rating_filter=rating_filter
    )


@app.route("/delete_review/<int:review_id>")
def delete_review(review_id):

    cur = mysql.connection.cursor()

    cur.execute(
        "DELETE FROM reviews WHERE id=%s",
        (review_id,)
    )

    mysql.connection.commit()

    cur.close()

    return redirect("/admin/reviews")


@app.route("/admin/coupons")
def admin_coupons():

    if "admin" not in session:
        return redirect("/admin_login")

    search = request.args.get("search", "").strip()

    cur = mysql.connection.cursor()

    # Automatically deactivate expired coupons
    cur.execute("""
        UPDATE coupons
        SET status='Inactive'
        WHERE expiry_date IS NOT NULL
        AND expiry_date < CURDATE()
        AND status='Active'
    """)

    mysql.connection.commit()

    # Get today's date
    cur.execute("SELECT CURDATE()")
    today = cur.fetchone()[0]

    # Get coupons
    query = """
        SELECT
            id,
            coupon_code,
            discount_percent,
            status,
            expiry_date
        FROM coupons
        WHERE 1=1
    """

    params = []

    # Search coupon code or status
    if search:

        query += """
            AND (
                coupon_code LIKE %s
                OR status LIKE %s
            )
        """

        search_value = "%" + search + "%"

        params.extend([
            search_value,
            search_value
        ])

    query += """
        ORDER BY id DESC
    """

    cur.execute(query, params)

    coupons = cur.fetchall()

    cur.close()

    return render_template(
        "admin_coupons.html",
        coupons=coupons,
        search=search,
        today=today
    )


@app.route("/add_coupon", methods=["POST"])
def add_coupon():

    coupon_code = request.form["coupon_code"].strip().upper()
    discount = request.form["discount"]
    expiry_date = request.form["expiry_date"]

    cur = mysql.connection.cursor()

    cur.execute("""
        INSERT INTO coupons
        (coupon_code, discount_percent, status, expiry_date)
        VALUES (%s, %s, 'Active', %s)
    """, (
        coupon_code,
        discount,
        expiry_date
    ))

    mysql.connection.commit()

    cur.close()

    return redirect("/admin/coupons")

@app.route("/toggle_coupon/<int:coupon_id>")
def toggle_coupon(coupon_id):

    cur = mysql.connection.cursor()

    cur.execute(
        "SELECT status FROM coupons WHERE id=%s",
        (coupon_id,)
    )

    status = cur.fetchone()[0]

    if status == "Active":
        new_status = "Inactive"
    else:
        new_status = "Active"

    cur.execute(
        "UPDATE coupons SET status=%s WHERE id=%s",
        (new_status, coupon_id)
    )

    mysql.connection.commit()

    cur.close()

    return redirect("/admin/coupons")

@app.route("/delete_coupon/<int:coupon_id>")
def delete_coupon(coupon_id):

    cur = mysql.connection.cursor()

    cur.execute(
        "DELETE FROM coupons WHERE id=%s",
        (coupon_id,)
    )

    mysql.connection.commit()

    cur.close()

    return redirect("/admin/coupons")


@app.route("/update_order_status/<int:order_id>", methods=["POST"])
def update_order_status(order_id):

    status = request.form["status"]

    cur = mysql.connection.cursor()

    # --------------------------------
    # GET CURRENT ORDER STATUS
    # --------------------------------

    cur.execute("""
        SELECT status
        FROM orders
        WHERE id=%s
    """, (order_id,))

    order = cur.fetchone()

    if not order:
        cur.close()
        return "Order not found!"

    old_status = order[0]

    # --------------------------------
    # RESTORE STOCK WHEN ADMIN CANCELS
    # --------------------------------

    if status == "Cancelled" and old_status != "Cancelled":

        cur.execute("""
            SELECT product_id, quantity
            FROM order_items
            WHERE order_id=%s
        """, (order_id,))

        items = cur.fetchall()

        for item in items:

            product_id = item[0]
            quantity = item[1]

            cur.execute("""
                UPDATE products
                SET stock = stock + %s
                WHERE id=%s
            """, (
                quantity,
                product_id
            ))

    # --------------------------------
    # GET CUSTOMER DETAILS
    # --------------------------------

    cur.execute("""
        SELECT
            users.email,
            orders.customer_name,
            orders.total
        FROM orders
        JOIN users
        ON orders.username = users.username
        WHERE orders.id=%s
    """, (order_id,))

    customer = cur.fetchone()

    # --------------------------------
    # UPDATE ORDER STATUS
    # --------------------------------

    cur.execute("""
        UPDATE orders
        SET status=%s
        WHERE id=%s
    """, (
        status,
        order_id
    ))

    # --------------------------------
    # SEND CANCELLATION EMAIL
    # --------------------------------

    if status == "Cancelled" and old_status != "Cancelled":

        if customer:

            customer_email = customer[0]
            customer_name = customer[1]
            total = customer[2]

            msg = Message(
                subject=f"❌ SVP Cafe Order #{order_id} - Order Cancelled",
                sender=app.config["MAIL_USERNAME"],
                recipients=[customer_email]
            )

            msg.body = f"""
Hello {customer_name},

We are sorry to inform you that your SVP Cafe order #{order_id} has been CANCELLED. ❌

Order Details
----------------------------------------

Order ID: #{order_id}
Total Amount: ₹{total}

Your order has been cancelled by SVP Cafe.

If you have any questions regarding this cancellation,
please contact SVP Cafe.

Thank you for choosing SVP Cafe! ☕

SVP Cafe Team
"""

            try:

                mail.send(msg)

                print(
                    "Order cancellation email sent successfully."
                )

            except Exception as e:

                print(
                    "Cancellation email sending failed:",
                    e
                )

    # --------------------------------
    # SEND OUT FOR DELIVERY EMAIL
    # --------------------------------

    if status == "Out for Delivery":

        if customer:

            customer_email = customer[0]
            customer_name = customer[1]
            total = customer[2]

            msg = Message(
                subject=f"🚚 SVP Cafe Order #{order_id} - Out for Delivery",
                sender=app.config["MAIL_USERNAME"],
                recipients=[customer_email]
            )

            msg.body = f"""
Hello {customer_name},

Your SVP Cafe order #{order_id} is now OUT FOR DELIVERY! 🚚

Your order is on the way and will arrive soon.

Order ID: #{order_id}
Total Amount: ₹{total}

Thank you for ordering from SVP Cafe! ☕

Enjoy your food!

SVP Cafe Team
"""

            try:

                mail.send(msg)

                print(
                    "Out for Delivery email sent successfully."
                )

            except Exception as e:

                print(
                    "Out for Delivery email sending failed:",
                    e
                )

    # --------------------------------
    # SAVE CHANGES
    # --------------------------------

    mysql.connection.commit()

    cur.close()

    return redirect("/view_orders")

@app.route("/cancel_order/<int:order_id>", methods=["POST"])
def cancel_order(order_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    # Check current order status
    cur.execute("""
        SELECT status
        FROM orders
        WHERE id=%s
        AND username=%s
    """, (order_id, username))

    order = cur.fetchone()

    if order:

        if order[0] == "Pending" or order[0] == "Preparing":

            # Get customer email and order details
            cur.execute("""
                SELECT
                    users.email,
                    orders.customer_name,
                    orders.total
                FROM orders
                JOIN users
                ON orders.username = users.username
                WHERE orders.id=%s
                AND orders.username=%s
            """, (order_id, username))

            customer = cur.fetchone()

            # Get all ordered products
            cur.execute("""
                SELECT product_id, quantity
                FROM order_items
                WHERE order_id=%s
            """, (order_id,))

            items = cur.fetchall()

            # Restore stock
            for item in items:

                product_id = item[0]
                quantity = item[1]

                cur.execute("""
                    UPDATE products
                    SET stock = stock + %s
                    WHERE id=%s
                """, (quantity, product_id))

            # Cancel order
            cur.execute("""
                UPDATE orders
                SET status='Cancelled'
                WHERE id=%s
            """, (order_id,))

            mysql.connection.commit()

            # Send cancellation email
            if customer:

                customer_email = customer[0]
                customer_name = customer[1]
                total = customer[2]

                msg = Message(
                    subject=f"❌ SVP Cafe Order #{order_id} Cancelled",
                    sender=app.config["MAIL_USERNAME"],
                    recipients=[customer_email]
                )

                msg.body = f"""
Hello {customer_name},

Your SVP Cafe order #{order_id} has been cancelled successfully.

Order ID: #{order_id}
Order Amount: ₹{total}
Status: Cancelled

Your ordered product stock has also been restored.

If you have any questions, please contact SVP Cafe.

Thank you,
SVP Cafe Team ☕
"""

                mail.send(msg)

    cur.close()

    return redirect("/order_history")

@app.route("/order_details/<int:order_id>")
def order_details(order_id):

    if "admin" not in session:
        return redirect("/admin_login")

    cur = mysql.connection.cursor()

    # Order information
    cur.execute("""
        SELECT *
        FROM orders
        WHERE id=%s
    """, (order_id,))

    order = cur.fetchone()

    # Ordered products
    cur.execute("""
        SELECT
            product_name,
            price,
            quantity,
            subtotal
        FROM order_items
        WHERE order_id=%s
    """, (order_id,))

    items = cur.fetchall()

    cur.close()

    return render_template(
        "order_details.html",
        order=order,
        items=items
    )


@app.route("/download_invoice/<int:order_id>")
def download_invoice(order_id):

    if "username" not in session:
        return redirect("/login")

    username = session["username"]

    cur = mysql.connection.cursor()

    # Get Order Details
    cur.execute("""
        SELECT
            customer_name,
            phone,
            address,
            payment_method,
            total,
            order_date,
            status
        FROM orders
        WHERE id=%s
        AND username=%s
    """, (order_id, username))

    order = cur.fetchone()

    if not order:
        cur.close()
        return "Order not found."

    # Get Ordered Products
    cur.execute("""
        SELECT
            product_name,
            quantity,
            price,
            subtotal
        FROM order_items
        WHERE order_id=%s
    """, (order_id,))

    items = cur.fetchall()

    cur.close()

    # Create PDF
    pdf_file = f"invoice_{order_id}.pdf"

    doc = SimpleDocTemplate(pdf_file)

    styles = getSampleStyleSheet()

    elements = []

    # Cafe Heading
    elements.append(Paragraph("<b><font size='22'>☕ SVP Cafe</font></b>", styles["Title"]))
    elements.append(Paragraph("<br/>", styles["Normal"]))

    elements.append(Paragraph(f"<b>Invoice No :</b> {order_id}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Date :</b> {order[5]}", styles["Normal"]))
    elements.append(Paragraph("<br/>", styles["Normal"]))

    # Customer Details
    elements.append(Paragraph("<b>Customer Details</b>", styles["Heading2"]))
    elements.append(Paragraph(f"Name : {order[0]}", styles["Normal"]))
    elements.append(Paragraph(f"Phone : {order[1]}", styles["Normal"]))
    elements.append(Paragraph(f"Address : {order[2]}", styles["Normal"]))
    elements.append(Paragraph("<br/>", styles["Normal"]))

    # Products Table
    data = [["Product", "Qty", "Price", "Subtotal"]]

    for item in items:
        data.append([
            item[0],
            str(item[1]),
            f"₹{item[2]}",
            f"₹{item[3]}"
        ])

    table = Table(data)

    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.brown),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),1,colors.black),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BOTTOMPADDING",(0,0),(-1,0),10),
        ("BACKGROUND",(0,1),(-1,-1),colors.beige),
    ]))

    elements.append(table)

    elements.append(Paragraph("<br/>", styles["Normal"]))

    # Summary
    elements.append(Paragraph(f"<b>Total Amount :</b> ₹{order[4]}", styles["Heading2"]))
    elements.append(Paragraph(f"<b>Payment Method :</b> {order[3]}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Order Status :</b> {order[6]}", styles["Normal"]))

    elements.append(Paragraph("<br/>", styles["Normal"]))
    elements.append(Paragraph("<b>Thank You for Visiting SVP Cafe! ☕</b>", styles["Heading2"]))
    elements.append(Paragraph("Visit Again!", styles["Normal"]))

    doc.build(elements)

    return send_file(
        pdf_file,
        as_attachment=True
    )

@app.route("/admin/sales_report")
def admin_sales_report():

    if "admin" not in session:
        return redirect("/admin_login")

    cur = mysql.connection.cursor()

    # Total Orders
    cur.execute("""
        SELECT COUNT(*)
        FROM orders
        WHERE status != 'Cancelled'
    """)
    total_orders = cur.fetchone()[0]

    # Total Revenue
    cur.execute("""
        SELECT COALESCE(SUM(total), 0)
        FROM orders
        WHERE status != 'Cancelled'
    """)
    total_revenue = cur.fetchone()[0]

    # Total Products Sold
    cur.execute("""
        SELECT COALESCE(SUM(oi.quantity), 0)
        FROM order_items oi
        JOIN orders o
        ON oi.order_id = o.id
        WHERE o.status != 'Cancelled'
    """)
    total_products_sold = cur.fetchone()[0]

    # Today's Revenue
    cur.execute("""
        SELECT COALESCE(SUM(total), 0)
        FROM orders
        WHERE DATE(order_date) = CURDATE()
        AND status != 'Cancelled'
    """)
    today_revenue = cur.fetchone()[0]

    # This Month's Revenue
    cur.execute("""
        SELECT COALESCE(SUM(total), 0)
        FROM orders
        WHERE MONTH(order_date) = MONTH(CURDATE())
        AND YEAR(order_date) = YEAR(CURDATE())
        AND status != 'Cancelled'
    """)
    month_revenue = cur.fetchone()[0]

    cur.close()

    return render_template(
        "sales_report.html",
        total_orders=total_orders,
        total_revenue=total_revenue,
        total_products_sold=total_products_sold,
        today_revenue=today_revenue,
        month_revenue=month_revenue
    )


if __name__ == "__main__":
    app.run()