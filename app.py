import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Product, Category, ProductImage

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_123'  # Нужно для работы сессий
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///market.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db.init_app(app)

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- МАРШРУТЫ АВТОРИЗАЦИИ ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким логином уже существует.', 'danger')
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))

        flash('Неверный логин или пароль.', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# --- ОСНОВНОЙ ФУНКЦИОНАЛ ---

# ==========================================
# 1. ГЛАВНАЯ СТРАНИЦА И ПОИСК
# ==========================================
@app.route('/')
def index():
    # Получаем параметры из URL (например: /?search=учебник&max_price=500)
    category_id = request.args.get('category_id')
    search_query = request.args.get('search')
    max_price = request.args.get('max_price')

    # Начинаем собирать запрос к БД
    query = Product.query

    if category_id:
        query = query.filter_by(category_id=category_id)

    if search_query:
        # ilike ищет без учета регистра (учебник == Учебник)
        query = query.filter(Product.title.ilike(f'%{search_query}%'))

    if max_price and max_price.isdigit():
        query = query.filter(Product.price <= int(max_price))

    products = query.order_by(Product.id.desc()).all()
    categories = Category.query.all()

    return render_template('index.html', products=products, categories=categories)


# ==========================================
# 5. ЛИЧНЫЙ КАБИНЕТ (ПРОФИЛЬ)
# ==========================================
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # Логика смены пароля
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')

        if check_password_hash(current_user.password_hash, old_password):
            current_user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Пароль успешно изменен!', 'success')
        else:
            flash('Неверный текущий пароль.', 'danger')
        return redirect(url_for('profile'))

    # Получаем только объявления текущего пользователя
    user_products = Product.query.filter_by(user_id=current_user.id).order_by(Product.id.desc()).all()
    return render_template('profile.html', products=user_products)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    # Ищем товар по ID. Если кто-то введет несуществующий ID, Flask выдаст ошибку 404
    product = Product.query.get_or_404(product_id)
    return render_template('product_detail.html', product=product)


@app.route('/add', methods=['GET', 'POST'])
@login_required  # Только залогиненные могут добавлять
def add_product():
    if request.method == 'POST':
        new_product = Product(
            title=request.form['title'],
            description=request.form['description'],
            price=request.form['price'],
            contact_link=request.form['contact'],
            category_id=request.form['category'],
            user_id=current_user.id  # Привязываем к текущему юзеру
        )
        db.session.add(new_product)
        db.session.flush()

        files = request.files.getlist('photos')
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db.session.add(ProductImage(filename=filename, product_id=new_product.id))

        db.session.commit()
        return redirect(url_for('index'))
    return render_template('add_product.html', categories=Category.query.all())


# --- ТРЕБОВАНИЕ: REST API ---
# Этот эндпоинт отдает список товаров в формате JSON. Отлично подойдет и для Алисы!
@app.route('/api/products', methods=['GET'])
def get_products_api():
    products = Product.query.all()
    output = []
    for p in products:
        p_data = {
            'id': p.id,
            'title': p.title,
            'price': p.price,
            'description': p.description,
            'category': p.category.name,
            'seller': p.seller.username,
            'images': [url_for('static', filename='uploads/' + img.filename, _external=True) for img in p.images]
        }
        output.append(p_data)
    return jsonify({'products': output})


# ==========================================
# 4. РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ ОБЪЯВЛЕНИЙ
# ==========================================

@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    # Строгая проверка прав
    if product.user_id != current_user.id:
        flash('Вы не можете редактировать чужие объявления!', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # 1. Сначала обрабатываем УДАЛЕНИЕ выбранных фотографий
        delete_images_ids = request.form.getlist('delete_images')  # Получаем список ID галочек
        if delete_images_ids:
            for img_id in delete_images_ids:
                image_to_del = ProductImage.query.get(int(img_id))
                # Дополнительная проверка: принадлежит ли фото этому товару
                if image_to_del and image_to_del.product_id == product.id:
                    # Чистим файл с диска
                    try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], image_to_del.filename))
                    except FileNotFoundError:
                        pass
                    # Чистим запись из БД
                    db.session.delete(image_to_del)

        # 2. Обновляем основные текстовые поля
        product.title = request.form.get('title')
        product.category_id = request.form.get('category')
        product.price = request.form.get('price', 0)
        product.description = request.form.get('description')
        product.contact_link = request.form.get('contact')

        # 3. Обрабатываем ДОБАВЛЕНИЕ новых фото
        files = request.files.getlist('photos')
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db.session.add(ProductImage(filename=filename, product_id=product.id))

        db.session.commit()
        flash('Объявление успешно обновлено!', 'success')
        return redirect(url_for('index'))

    categories = Category.query.all()
    return render_template('edit_product.html', product=product, categories=categories)


@app.route('/delete/<int:product_id>', methods=['POST', 'GET'])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)

    # Проверка прав
    if product.user_id != current_user.id:
        flash('Вы не можете удалить чужое объявление!', 'danger')
        return redirect(url_for('index'))

    # Удаляем файлы картинок с жесткого диска сервера, чтобы не забивать место
    for img in product.images:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], img.filename))
        except FileNotFoundError:
            pass  # Если файла физически нет, просто идем дальше
        db.session.delete(img)

    # Удаляем сам товар из базы
    db.session.delete(product)
    db.session.commit()

    flash('Объявление успешно удалено.', 'success')
    return redirect(url_for('index'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Category.query.first():
            db.session.add_all([Category(name="Учебники"), Category(name="Техника"), Category(name="Спорт")])
            db.session.commit()
    app.run(debug=True)
